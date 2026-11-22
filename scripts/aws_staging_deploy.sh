#!/usr/bin/env bash
#
# Deploy the OceanAI water staging environment.
#
# NOT RUN. This script is written, reviewed and costed, but no AWS resource
# it creates exists: the decision was to deliver the infrastructure and the
# runbook without spending. Read it as the procedure, not as a record.
#
# It is deliberately ordinary: build, push, create the stack, migrate, load,
# verify. Every expensive step is a one-off task, and the web service is
# never the thing that ingests.
#
#   bash scripts/aws_staging_deploy.sh
#
# Requires: aws CLI v2 with credentials, docker, and a VPC with two public
# subnets in different availability zones.
set -euo pipefail

STACK=${STACK:-oceanai-water-staging}
REGION=${AWS_REGION:-ap-south-1}
REPO=${ECR_REPO:-oceanai/backend}
VPC_ID=${VPC_ID:?set VPC_ID}
SUBNET_IDS=${SUBNET_IDS:?set SUBNET_IDS as a comma-separated list of two public subnets}

cd "$(dirname "$0")/.."
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG="staging-$(git rev-parse --short HEAD)"
IMAGE="${REGISTRY}/${REPO}:${TAG}"

say() { printf '\n=== %s ===\n' "$*"; }

say "1/7 build the image"
docker build -f docker/Dockerfile.backend -t "${IMAGE}" .

say "2/7 push to ECR"
aws ecr describe-repositories --repository-names "${REPO}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${REPO}" --region "${REGION}" >/dev/null
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"
docker push "${IMAGE}"

say "3/7 create or update the stack"
# CAPABILITY_IAM: the template creates the task, execution and scheduler
# roles. They are scoped in the template; none is administrative.
aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${STACK}" \
  --template-file infra/aws/staging.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      VpcId="${VPC_ID}" \
      SubnetIds="${SUBNET_IDS}" \
      ImageUri="${IMAGE}" \
  --tags project=oceanai-water-staging

outputs() {
  aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK}" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

CLUSTER=$(outputs ClusterName)
JOB_TASK=$(outputs JobTaskDefinitionArn)
URL=$(outputs ServiceUrl)
SUBNET_JSON=$(printf '"%s",' ${SUBNET_IDS//,/ } | sed 's/,$//')
SG=$(aws cloudformation describe-stack-resources --region "${REGION}" --stack-name "${STACK}" \
      --logical-resource-id ServiceSecurityGroup --query 'StackResources[0].PhysicalResourceId' --output text)

run_job() {
  # Run one command in the job task definition and wait for it to finish.
  local name="$1"; shift
  local command_json
  command_json=$(printf '"%s",' "$@" | sed 's/,$//')
  say "job: ${name}"
  local arn
  arn=$(aws ecs run-task --region "${REGION}" --cluster "${CLUSTER}" \
    --task-definition "${JOB_TASK}" --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_JSON}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
    --overrides "{\"containerOverrides\":[{\"name\":\"job\",\"command\":[${command_json}]}]}" \
    --query 'tasks[0].taskArn' --output text)
  aws ecs wait tasks-stopped --region "${REGION}" --cluster "${CLUSTER}" --tasks "${arn}"
  aws ecs describe-tasks --region "${REGION}" --cluster "${CLUSTER}" --tasks "${arn}" \
    --query 'tasks[0].containers[0].{exit:exitCode,reason:reason}' --output table
}

WITH_DB='export DATABASE_URL="postgresql+psycopg://$PGUSER:$PGPASSWORD@$PGHOST:5432/$PGDATABASE" &&'

say "4/7 migrate (before anything reads the schema)"
run_job migrate /bin/sh -c "${WITH_DB} python -m app.water.cli db upgrade"

say "5/7 seed reference data and the research corpus"
run_job seed /bin/sh -c "${WITH_DB} python -m app.water.cli seed-standards && python -m app.water.cli reindex-water-rag"

say "6/7 first data load"
# Start with the real-time feed: it is small, current, and proves outbound
# access to the CPCB portal from inside the VPC. The national manual extracts
# take tens of minutes and can follow on the schedule.
run_job sync-realtime /bin/sh -c "${WITH_DB} python -m app.water.cli sync-water-data --provider cpcb_rtwqms --all"
run_job boundaries /bin/sh -c "${WITH_DB} python -m app.water.cli import-boundaries && python -m app.water.cli import-cities"

say "7/7 verify"
echo "service: ${URL}"
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${URL}/api/v1/health/ready" || true)
  [ "${code}" = "200" ] && break
  sleep 15
done
curl -s --max-time 20 "${URL}/api/v1/health" | head -c 400; echo
curl -s --max-time 20 "${URL}/api/v1/water-jobs" | head -c 400; echo

cat <<NOTE

Deployed: ${URL}

What is deliberately NOT automatic:
  * the national manual extracts (cpcb_nwdp, cwc_nwdp) -- tens of minutes;
    the weekly schedule picks them up, or run them now with
    run_job sync-manual ... --provider cpcb_nwdp --all
  * geometry, which needs the OSM extract on a volume the job can read;
  * satellite processing, which the weekly schedule runs.

Tear down with: bash scripts/aws_staging_teardown.sh
NOTE
