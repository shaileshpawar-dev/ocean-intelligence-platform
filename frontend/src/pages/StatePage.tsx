/**
 * State page.
 *
 * Counts are derived from ingested records only. A state with no ingested
 * extract shows an explicit empty state rather than zeros, because "we have
 * not loaded this state" and "this state has no water bodies" are entirely
 * different statements.
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import {
  STATUS_META,
  StatCard,
  TYPE_META,
  WaterStatusBadge,
  formatDay,
} from "@/components/water";
import type { WaterBodyType, WaterStatus } from "@/lib/waterTypes";

export default function StatePage() {
  const { slug = "" } = useParams();
  const state = useQuery({
    queryKey: ["state", slug],
    queryFn: () => api.state(slug),
    enabled: Boolean(slug),
  });

  if (state.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (state.isError) {
    return (
      <ErrorState
        error={state.error}
        onRetry={() => state.refetch()}
        emptyTitle="State not ingested"
        emptyHint="No CPCB extract has been ingested for this state yet. That is a coverage gap, not an absence of water bodies."
      />
    );
  }

  const data = state.data;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={`${data.name} water intelligence`}
        subtitle={`${data.water_body_count} water bodies · ${data.station_count} monitoring stations · ${data.observation_count.toLocaleString()} observations`}
        actions={
          <Link className="btn btn-outline btn-sm" to="/app/india">
            <ArrowLeft size={13} /> All states
          </Link>
        }
      />

      <div className="stat-row">
        <StatCard label="Water bodies" value={data.water_body_count} />
        <StatCard label="Monitoring stations" value={data.station_count} />
        <StatCard
          label="Observations"
          value={data.observation_count.toLocaleString()}
        />
        <StatCard
          label="Latest observation"
          value={formatDay(data.latest_observed_at)}
          hint="Most recent sample anywhere in this state"
        />
      </div>

      <div className="two-col">
        <SectionCard title="By water body type">
          <ul className="dist-list">
            {Object.entries(data.by_type).map(([type, count]) => (
              <li key={type}>
                <div className="dist-row">
                  <span className="dist-label">
                    {TYPE_META[type as WaterBodyType]?.label ?? type}
                  </span>
                  <span className="dist-count">{count}</span>
                </div>
              </li>
            ))}
          </ul>
        </SectionCard>

        <SectionCard
          title="Status when last measured"
          description="What each water body's most recent sample found — each with its own date on the detail page. Present-tense status is 'no recent data' wherever the source has not published lately."
        >
          <ul className="dist-list">
            {Object.entries(data.historical_status_distribution).map(([status, count]) => (
              <li key={status}>
                <div className="dist-row">
                  <span className="dist-label">
                    {STATUS_META[status as WaterStatus]?.label ?? status}
                  </span>
                  <span className="dist-count">{count}</span>
                </div>
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>

      <SectionCard
        title="Most-monitored water bodies"
        description="Ranked by status severity when last measured, then by how much data supports them."
      >
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Water body</th>
                <th>Type</th>
                <th>District</th>
                <th>When last measured</th>
                <th>Latest</th>
                <th className="num">Obs.</th>
              </tr>
            </thead>
            <tbody>
              {data.notable.map((body) => (
                <tr key={body.slug}>
                  <td>
                    <Link to={`/app/water/${body.slug}`}>{body.name}</Link>
                  </td>
                  <td>{TYPE_META[body.water_type]?.label ?? body.water_type}</td>
                  <td>{body.district ?? "—"}</td>
                  <td>
                    <WaterStatusBadge
                      status={body.latest_available_status}
                      size="sm"
                    />
                  </td>
                  <td>{formatDay(body.latest_observed_at)}</td>
                  <td className="num">{body.observation_count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title={`Districts (${data.districts.length})`}>
        <div className="district-grid">
          {data.districts.map((district) => (
            <Link
              className="district-card"
              key={district.slug}
              to={`/app/city/${district.slug}`}
            >
              <span className="district-name">
                <MapPin size={12} aria-hidden /> {district.name}
              </span>
              <span className="muted-note">
                {district.water_body_count} water bodies
              </span>
            </Link>
          ))}
        </div>
      </SectionCard>
    </>
  );
}
