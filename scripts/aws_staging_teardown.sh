#!/usr/bin/env bash
#
# Remove the OceanAI water staging environment and stop it costing anything.
#
# NOT RUN: nothing described here exists. Written so that deploying is a
# reversible decision rather than a standing charge somebody forgets.
#
#   bash scripts/aws_staging_teardown.sh            # keep the data
#   DELETE_EVIDENCE=yes bash scripts/aws_staging_teardown.sh
#
# What survives on purpose:
#   * a final RDS snapshot (the template's DeletionPolicy), so the database
#     can be restored;
#   * the S3 evidence bucket, which is Retain -- satellite scenes cost real
#     processing to produce and a teardown is not a reason to lose them.
# Both are named at the end so they can be removed deliberately.
set -euo pipefail

STACK=${STACK:-oceanai-water-staging}
REGION=${AWS_REGION:-ap-south-1}

say() { printf '\n=== %s ===\n' "$*"; }

if ! aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK}" >/dev/null 2>&1; then
  echo "Stack ${STACK} does not exist in ${REGION}. Nothing to do."
  exit 0
fi

say "what will go"
aws cloudformation describe-stack-resources --region "${REGION}" --stack-name "${STACK}" \
  --query 'StackResources[].{type:ResourceType,id:PhysicalResourceId}' --output table

BUCKET=$(aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='EvidenceBucketName'].OutputValue" --output text 2>/dev/null || true)

say "scale the service to zero first"
# Deleting a service with running tasks works, but draining first keeps the
# logs readable and the deletion quick.
CLUSTER=$(aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='ClusterName'].OutputValue" --output text)
aws ecs update-service --region "${REGION}" --cluster "${CLUSTER}" \
  --service oceanai-water-staging-web --desired-count 0 >/dev/null 2>&1 || true

say "delete the stack"
aws cloudformation delete-stack --region "${REGION}" --stack-name "${STACK}"
echo "waiting for the stack to go (the RDS snapshot takes a few minutes)..."
aws cloudformation wait stack-delete-complete --region "${REGION}" --stack-name "${STACK}"
echo "stack deleted."

say "what is left, deliberately"
aws rds describe-db-snapshots --region "${REGION}" \
  --query "DBSnapshots[?starts_with(DBSnapshotIdentifier, 'oceanai-water-staging')].{id:DBSnapshotIdentifier,created:SnapshotCreateTime,gb:AllocatedStorage}" \
  --output table || true

if [ -n "${BUCKET}" ] && [ "${BUCKET}" != "None" ]; then
  echo "evidence bucket retained: ${BUCKET}"
  if [ "${DELETE_EVIDENCE:-no}" = "yes" ]; then
    say "deleting the evidence bucket, as asked"
    aws s3 rm "s3://${BUCKET}" --recursive --region "${REGION}"
    aws s3api delete-bucket --bucket "${BUCKET}" --region "${REGION}"
    echo "bucket deleted."
  else
    echo "  keep it, or: DELETE_EVIDENCE=yes bash scripts/aws_staging_teardown.sh"
  fi
fi

cat <<NOTE

Ongoing cost after teardown: the RDS snapshot (a few cents a month per GB
beyond the free allowance) and whatever is in S3. Everything hourly -- the
load balancer, the Fargate task, the database instance -- is gone.
NOTE
