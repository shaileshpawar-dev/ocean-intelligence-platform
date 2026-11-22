/**
 * City / district page.
 *
 * A curated city is an explicit grouping of whole districts (Greater Mumbai
 * is the Mumbai and Mumbai Suburban districts), written down with a note on
 * what the grouping means. A slug that is not a curated city shows the
 * district of that name. Either way the page says which it is.
 */

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, CircleMarker, TileLayer, Tooltip } from "react-leaflet";
import { ArrowLeft, Info, MapPin } from "lucide-react";
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
        emptyTitle="City or district not found"
        emptyHint="No curated city or district with this identifier exists in the data."
      />
    );
  }

  const data = city.data;
  if (!data) return null;

  const isCity = data.kind === "city";
  const located = data.water_bodies.filter(
    (b) => b.latitude != null && b.longitude != null,
  );

  return (
    <>
      <PageHeader
        title={data.name}
        subtitle={`${isCity ? "City" : "District"}${data.state ? ` · ${data.state}` : ""}`}
        actions={
          <>
            <Link className="btn btn-outline btn-sm" to={`/app/map?city=${data.slug}`}>
              <MapPin size={13} /> View on map
            </Link>
            {data.state_slug && (
              <Link className="btn btn-outline btn-sm" to={`/app/state/${data.state_slug}`}>
                <ArrowLeft size={13} /> {data.state}
              </Link>
            )}
          </>
        }
      />

      {isCity && (
        <SectionCard title="What this city means here">
          <p>{data.definition}</p>
          {data.districts && data.districts.length > 0 && (
            <p className="muted-note">
              CPCB districts included:{" "}
              {data.districts.map((d, i) => (
                <span key={d.slug}>
                  {i > 0 && ", "}
                  <Link to={`/app/city/${d.slug}`}>{d.name}</Link>
                </span>
              ))}
            </p>
          )}
          <p className="muted-note">Extent: {data.position_source}</p>
          {data.latest_observed_at && (
            <p className="muted-note">
              Latest available observation in this city: {formatDay(data.latest_observed_at)}.
              The current condition cannot be established from this dataset.
            </p>
          )}
        </SectionCard>
      )}

      {data.empty_reason && (
        <SectionCard>
          <p className="muted-note">
            <Info size={13} aria-hidden /> {data.empty_reason} This is an absence of monitoring
            data, not evidence about water quality.
          </p>
        </SectionCard>
      )}

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
          description="Water bodies are placed at the mean position of their monitoring stations."
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
