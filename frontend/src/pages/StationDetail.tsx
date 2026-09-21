/**
 * Monitoring station detail.
 *
 * A station answers a narrower question than a water body: what did this
 * specific sampling point find, and when? Values are therefore per-parameter
 * latest rather than rolled up, and each carries its own observation date —
 * a station may have measured pH last December and lead only once in 2019.
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, CircleMarker, TileLayer } from "react-leaflet";
import { ArrowLeft, Building2, MapPin } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import {
  FreshnessNote,
  LatestAvailableStatus,
  ParameterCard,
  WaterStatusBadge,
  formatDay,
} from "@/components/water";

export default function StationDetail() {
  const { stationId = "" } = useParams();
  const id = Number(stationId);

  const station = useQuery({
    queryKey: ["station", id],
    queryFn: () => api.station(id),
    enabled: Number.isFinite(id) && id > 0,
  });

  if (station.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (station.isError) {
    return (
      <ErrorState
        error={station.error}
        onRetry={() => station.refetch()}
        emptyTitle="Station not found"
        emptyHint="No monitoring station with this id exists in the ingested data."
      />
    );
  }

  const data = station.data;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={data.name}
        subtitle="Monitoring station"
        actions={
          data.water_body_slug ? (
            <Link
              className="btn btn-outline btn-sm"
              to={`/app/water/${data.water_body_slug}`}
            >
              <ArrowLeft size={13} /> {data.water_body}
            </Link>
          ) : undefined
        }
      />

      <div className="wb-tags">
        {data.agency && (
          <span className="chip">
            <Building2 size={12} aria-hidden /> {data.agency}
          </span>
        )}
        {data.district && <span className="chip">{data.district}</span>}
        <span className="chip">{data.observation_count} observations</span>
        {data.geo_quality !== "ok" && (
          <span className="chip chip-warn">
            Coordinates {data.geo_quality}
          </span>
        )}
      </div>

      <div className="wb-status-grid">
        <SectionCard title="Right now">
          <WaterStatusBadge status={data.status_detail.status} />
          <FreshnessNote detail={data.status_detail} />
        </SectionCard>

        <SectionCard title="When last measured">
          {data.latest_available_status ? (
            <LatestAvailableStatus
              detail={data.latest_available_status}
              observedAt={data.latest_observed_at}
            />
          ) : (
            <p className="muted-note">No measurements recorded at this station.</p>
          )}
        </SectionCard>
      </div>

      <SectionCard
        title="Latest values"
        description="Most recent value for each parameter this station has measured, each with its own date."
      >
        {data.parameters.length === 0 ? (
          <p className="muted-note">No parameter values recorded.</p>
        ) : (
          <div className="param-grid">
            {data.parameters.map((reading) => (
              <ParameterCard key={reading.parameter} reading={reading} />
            ))}
          </div>
        )}
      </SectionCard>

      {data.latitude != null && data.longitude != null && (
        <SectionCard title="Location">
          <MapContainer
            center={[data.latitude, data.longitude]}
            zoom={13}
            scrollWheelZoom={false}
            style={{ height: 260, borderRadius: 12 }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <CircleMarker
              center={[data.latitude, data.longitude]}
              radius={8}
              pathOptions={{
                color: "#ffffff",
                weight: 2,
                fillColor: "#1e40af",
                fillOpacity: 0.9,
              }}
            />
          </MapContainer>
          <p className="muted-note">
            <MapPin size={12} /> {data.latitude.toFixed(5)},{" "}
            {data.longitude.toFixed(5)} · latest observation{" "}
            {formatDay(data.latest_observed_at)}
          </p>
        </SectionCard>
      )}
    </>
  );
}
