/**
 * India overview — the landing dashboard for the water platform.
 *
 * Every counter here is a count of ingested records. Nothing is a target, an
 * estimate or a rounded-up headline. The number of water bodies *without*
 * recent data is given the same prominence as the flattering numbers,
 * because a monitoring platform that hides its coverage gaps is telling its
 * most important lie by omission.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Database, Droplets, MapPin, Radio } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import { STATUS_META, StatCard, formatDay } from "@/components/water";
import type { WaterStatus } from "@/lib/waterTypes";

export default function IndiaOverview() {
  const overview = useQuery({
    queryKey: ["water-overview"],
    queryFn: api.waterOverview,
  });
  const states = useQuery({ queryKey: ["states"], queryFn: api.states });

  if (overview.isLoading) return <LoadingSkeleton rows={4} height={92} />;
  if (overview.isError) {
    return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;
  }

  const data = overview.data;
  if (!data) return null;

  const distribution = Object.entries(data.historical_status_distribution).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <>
      <PageHeader
        title="India Water Intelligence"
        subtitle="What is currently known about India's monitored rivers, lakes, ponds and coastal waters — and how current that knowledge actually is."
        actions={
          <Link className="btn btn-primary btn-sm" to="/app/map">
            <MapPin size={13} /> Open the map
          </Link>
        }
      />

      <div className="stat-row">
        <StatCard
          label="Water bodies"
          value={data.water_bodies.toLocaleString()}
          hint="Resolved from monitoring station records"
        />
        <StatCard
          label="Monitoring stations"
          value={data.monitoring_stations.toLocaleString()}
          hint="Physical sampling locations"
        />
        <StatCard
          label="Observations"
          value={data.observations.toLocaleString()}
          hint="Individual parameter measurements"
        />
        <StatCard
          label="Without recent data"
          value={data.without_recent_data.toLocaleString()}
          hint="Too old to describe present conditions"
          tone={data.without_recent_data > 0 ? "warn" : "neutral"}
        />
      </div>

      <SectionCard
        title="How current is this?"
        description="The single most important thing to understand before reading anything else on this platform."
      >
        <div className="currency-note">
          <CalendarClock size={18} aria-hidden />
          <div>
            <p>
              The most recent observation anywhere in the ingested data is from{" "}
              <strong>{formatDay(data.latest_observation_at)}</strong>, and{" "}
              <strong>
                {(
                  data.water_bodies - data.without_recent_data
                ).toLocaleString()}
              </strong>{" "}
              of {data.water_bodies.toLocaleString()} water bodies have data
              recent enough to describe them now.
            </p>
            <p className="muted-note">
              That small number is the whole picture. CPCB runs automatic
              analysers on the Ganga and its tributaries that report hourly, so
              those water bodies can be described in the present tense. Every
              other water body here comes from manual sampling programmes whose
              published extracts lag years behind — CPCB's mostly stop in 2021
              — and for those the platform reports the{" "}
              <em>latest available</em> observation and its date, and refuses
              to describe present condition from it. Where you see a status,
              check the date attached to it.
            </p>
          </div>
        </div>
      </SectionCard>

      <div className="two-col">
        <SectionCard
          title="Status when last measured"
          description="What the most recent sample found at each water body — each with its own date on the detail page."
        >
          {distribution.length === 0 ? (
            <p className="muted-note">No water bodies ingested yet.</p>
          ) : (
            <ul className="dist-list">
              {distribution.map(([status, count]) => {
                const meta = STATUS_META[status as WaterStatus];
                const pct = data.water_bodies
                  ? Math.round((count / data.water_bodies) * 100)
                  : 0;
                return (
                  <li key={status}>
                    <div className="dist-row">
                      <span className="dist-label">
                        {meta?.label ?? status}
                      </span>
                      <span className="dist-count">
                        {count} ({pct}%)
                      </span>
                    </div>
                    <div className="dist-bar">
                      <span
                        className={`dist-fill dist-${meta?.tone ?? "unknown"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="Coverage"
          description="Geography actually present in the ingested data."
        >
          <div className="kv">
            <span>States and union territories</span>
            <span className="mono">{data.states_covered}</span>
          </div>
          <div className="kv">
            <span>Districts</span>
            <span className="mono">{data.districts_covered}</span>
          </div>

          {states.data && states.data.items.length > 0 && (
            <ul className="state-list">
              {states.data.items.map((state) => (
                <li key={state.code}>
                  <Link to={`/app/state/${state.slug}`}>
                    <span>{state.name}</span>
                    <span className="muted-note">
                      {state.water_body_count} water bodies ·{" "}
                      {state.station_count} stations
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <p className="muted-note">
            <Droplets size={12} /> Only states whose CPCB extracts have been
            ingested appear here. The source publishes 35; running ingestion
            for more states adds them without any code change.
          </p>
        </SectionCard>
      </div>

      <SectionCard
        title="Data sources"
        description="Where this platform's numbers come from, and whether each source is currently reachable."
        actions={<Database size={15} className="text-muted" />}
      >
        {data.sources.map((source) => (
          <div className="kv" key={source.key}>
            <span>
              {source.name}
              <br />
              <span className="muted-note">{source.organisation}</span>
            </span>
            <span>
              <span
                className={`wstatus wstatus-${source.is_available ? "ok" : "bad"} wstatus-sm`}
              >
                <Radio size={11} aria-hidden />
                {source.is_available ? "Available" : "Unavailable"}
              </span>
              <br />
              <span className="muted-note">
                cadence {source.expected_cadence} · last sync{" "}
                {formatDay(source.last_success_at)}
              </span>
            </span>
          </div>
        ))}

        {data.last_ingestion && (
          <p className="muted-note">
            Last ingestion run <code>{data.last_ingestion.run_id}</code> —{" "}
            {data.last_ingestion.status}, {data.last_ingestion.records_inserted.toLocaleString()}{" "}
            records inserted, finished {formatDay(data.last_ingestion.finished_at)}.
          </p>
        )}
      </SectionCard>
    </>
  );
}
