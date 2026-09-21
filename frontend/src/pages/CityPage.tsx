/**
 * City / district page.
 *
 * Districts double as the platform's city unit. Indian monitoring data is
 * keyed to districts, and the places people actually search for — Mumbai,
 * Pune, Bengaluru — are districts in that data. Inventing a separate city
 * table would mean inventing city boundaries the source never supplied, so
 * the page is honest about being a district view.
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, CircleMarker, TileLayer, Tooltip } from "react-leaflet";
import { ArrowLeft, Info } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import {
  StatCard,
  TYPE_META,
  WaterStatusBadge,
  formatDay,
} from "@/components/water";
import type { WaterBodyType } from "@/lib/waterTypes";

export default function CityPage() {
  const { slug = "" } = useParams();
  const city = useQuery({
    queryKey: ["city", slug],
    queryFn: () => api.city(slug),
    enabled: Boolean(slug),
  });

  if (city.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (city.isError) {
    return (
      <ErrorState
        error={city.error}
        onRetry={() => city.refetch()}
        emptyTitle="District not found"
        emptyHint="No district with this identifier exists in the ingested data."
      />
    );
  }

  const data = city.data;
  if (!data) return null;

  const located = data.water_bodies.filter(
    (b) => b.latitude != null && b.longitude != null,
  );

  return (
    <>
      <PageHeader
        title={data.name}
        subtitle={`District · ${data.state}`}
        actions={
          <Link className="btn btn-outline btn-sm" to={`/app/state/${data.state_slug}`}>
            <ArrowLeft size={13} /> {data.state}
          </Link>
        }
      />

      <div className="stat-row">
        <StatCard label="Water bodies" value={data.water_body_count} />
        <StatCard label="Monitoring stations" value={data.station_count} />
        {Object.entries(data.by_type)
          .slice(0, 2)
          .map(([type, count]) => (
            <StatCard
              key={type}
              label={TYPE_META[type as WaterBodyType]?.label ?? type}
              value={count}
            />
          ))}
      </div>

      {data.latitude != null && data.longitude != null && located.length > 0 && (
        <SectionCard
          title="Map"
          description="District centre is the mean position of its monitoring stations — the source publishes no district boundary."
        >
          <MapContainer
            center={[data.latitude, data.longitude]}
            zoom={11}
            scrollWheelZoom={false}
            style={{ height: 340, borderRadius: 12 }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {located.map((body) => (
              <CircleMarker
                key={body.slug}
                center={[body.latitude as number, body.longitude as number]}
                radius={7}
                pathOptions={{
                  color: "#ffffff",
                  weight: 1.5,
                  fillColor:
                    body.latest_available_status === "POLLUTED_STRETCH"
                      ? "#9b1c1c"
                      : body.latest_available_status === "HIGH_CONCERN"
                        ? "#e02424"
                        : body.latest_available_status === "ELEVATED"
                          ? "#d97706"
                          : body.latest_available_status === "WITHIN_REFERENCE"
                            ? "#0e9f6e"
                            : "#94a3b8",
                  fillOpacity: 0.85,
                }}
              >
                <Tooltip>
                  <strong>{body.name}</strong>
                  <br />
                  {formatDay(body.latest_observed_at)}
                </Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </SectionCard>
      )}

      <SectionCard title={`Water bodies (${data.water_bodies.length})`}>
        {data.water_bodies.length === 0 ? (
          <p className="muted-note">
            <Info size={13} /> No water bodies are recorded in this district.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Water body</th>
                  <th>Type</th>
                  <th>When last measured</th>
                  <th>Latest</th>
                  <th className="num">Obs.</th>
                </tr>
              </thead>
              <tbody>
                {data.water_bodies.map((body) => (
                  <tr key={body.slug}>
                    <td>
                      <Link to={`/app/water/${body.slug}`}>{body.name}</Link>
                    </td>
                    <td>{TYPE_META[body.water_type]?.label ?? body.water_type}</td>
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
        )}
      </SectionCard>

      <SectionCard title={`Monitoring stations (${data.stations.length})`}>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Station</th>
                <th>Water body</th>
                <th className="num">Observations</th>
                <th>Latest</th>
              </tr>
            </thead>
            <tbody>
              {data.stations.map((station) => (
                <tr key={station.id}>
                  <td>
                    <Link to={`/app/stations/${station.id}`}>{station.name}</Link>
                  </td>
                  <td>
                    {station.water_body_slug ? (
                      <Link to={`/app/water/${station.water_body_slug}`}>
                        {station.water_body}
                      </Link>
                    ) : (
                      <span className="muted-note">Not identified</span>
                    )}
                  </td>
                  <td className="num">{station.observation_count}</td>
                  <td>{formatDay(station.latest_observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </>
  );
}
