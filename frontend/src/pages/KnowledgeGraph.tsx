/**
 * Knowledge Graph.
 *
 * Solid edges are declared foreign keys. Dashed ones are citations resolved
 * from reports.sources -- real stored identifiers, but a JSON column rather
 * than a relationship, so nothing in the schema stops them dangling and the
 * weaker guarantee is drawn differently.
 *
 * Nothing is inferred from proximity, name similarity or an embedding, which
 * is why the empty state says "no linked records" rather than drawing
 * something suggestive.
 *
 * Layout is radial rather than force-directed, and deliberately so: the API
 * returns a subgraph defined by a centre and a hop count, and concentric rings
 * say "one hop" and "two hops" directly. It is also deterministic, so the
 * picture does not rearrange itself between renders, and it needs no graph
 * library — see PROGRESS.md for that decision.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info, Network } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import type { GraphEdge, GraphNode } from "@/lib/types";

/** Node colours. Chosen for contrast against both themes, not for prettiness. */
const TYPE_COLOUR: Record<string, string> = {
  region: "#2563eb",
  pollution_event: "#dc2626",
  satellite_observation: "#0891b2",
  risk_assessment: "#d97706",
  agent_run: "#7c3aed",
  report: "#4338ca",
  research_document: "#9333ea",
  sar_candidate: "#059669",
  sar_review: "#0d9488",
  optical_evidence: "#65a30d",
  vessel: "#be185d",
};

const TYPE_LABEL: Record<string, string> = {
  region: "Region",
  pollution_event: "Pollution event",
  satellite_observation: "Satellite observation",
  risk_assessment: "Risk assessment",
  agent_run: "Agent run",
  report: "Report",
  research_document: "Document / regulation",
  sar_candidate: "SAR candidate",
  sar_review: "Analyst review",
  optical_evidence: "Optical evidence",
  vessel: "Vessel",
};

const WIDTH = 760;
const HEIGHT = 520;
const RING = [0, 150, 240];

type Placed = GraphNode & { x: number; y: number; depth: number };

/** Hop distance from the centre, walked over the edges the API returned. */
function depths(centre: string, edges: GraphEdge[]): Map<string, number> {
  const neighbours = new Map<string, string[]>();
  for (const edge of edges) {
    if (!neighbours.has(edge.source)) neighbours.set(edge.source, []);
    if (!neighbours.has(edge.target)) neighbours.set(edge.target, []);
    neighbours.get(edge.source)!.push(edge.target);
    neighbours.get(edge.target)!.push(edge.source);
  }
  const seen = new Map<string, number>([[centre, 0]]);
  const queue = [centre];
  while (queue.length) {
    const id = queue.shift()!;
    const d = seen.get(id)!;
    for (const next of neighbours.get(id) ?? []) {
      if (!seen.has(next)) {
        seen.set(next, d + 1);
        queue.push(next);
      }
    }
  }
  return seen;
}

function layout(centre: string, nodes: GraphNode[], edges: GraphEdge[]): Placed[] {
  const depthOf = depths(centre, edges);
  const rings = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    // Anything the walk could not reach sits on the outermost ring rather
    // than being dropped: a node the API returned is a node that exists.
    const depth = Math.min(depthOf.get(node.id) ?? 2, RING.length - 1);
    if (!rings.has(depth)) rings.set(depth, []);
    rings.get(depth)!.push(node);
  }

  const placed: Placed[] = [];
  for (const [depth, group] of [...rings.entries()].sort((a, b) => a[0] - b[0])) {
    // Group by type around the ring so the same kind of record sits together.
    const ordered = [...group].sort(
      (a, b) => a.type.localeCompare(b.type) || a.id.localeCompare(b.id),
    );
    const radius = RING[depth] ?? RING[RING.length - 1];
    ordered.forEach((node, index) => {
      if (radius === 0) {
        placed.push({ ...node, x: 0, y: 0, depth });
        return;
      }
      const angle = (2 * Math.PI * index) / ordered.length - Math.PI / 2;
      placed.push({
        ...node,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius * 0.78,
        depth,
      });
    });
  }
  return placed;
}

export default function KnowledgeGraph() {
  const [centre, setCentre] = useState<{ type: string; id: string } | null>(null);
  const [depth, setDepth] = useState(2);
  const [hovered, setHovered] = useState<Placed | null>(null);

  const summary = useQuery({
    queryKey: ["kg-summary"],
    queryFn: api.knowledgeGraphSummary,
  });
  const zones = useQuery({ queryKey: ["zones", 300], queryFn: () => api.zones(300) });
  const graph = useQuery({
    queryKey: ["kg", centre?.type, centre?.id, depth],
    queryFn: () =>
      api.knowledgeGraph({
        centerType: centre?.type,
        centerId: centre?.id,
        depth,
      }),
    placeholderData: (previous) => previous,
  });

  const placed = useMemo(() => {
    if (!graph.data?.center) return [];
    return layout(graph.data.center, graph.data.nodes, graph.data.edges);
  }, [graph.data]);

  const positions = useMemo(
    () => new Map(placed.map((node) => [node.id, node])),
    [placed],
  );

  const presentTypes = useMemo(
    () => [...new Set(placed.map((node) => node.type))].sort(),
    [placed],
  );

  /** The centre's region code, so the selector shows what is actually drawn. */
  const centreRegionCode = useMemo(() => {
    if (!graph.data?.center) return "";
    const node = graph.data.nodes.find((n) => n.id === graph.data!.center);
    if (node?.type !== "region") return "";
    return typeof node.attrs.code === "string" ? node.attrs.code : "";
  }, [graph.data]);

  if (graph.isLoading && !graph.data) return <LoadingSkeleton rows={3} height={120} />;
  if (graph.isError) {
    return <ErrorState error={graph.error} onRetry={() => graph.refetch()} />;
  }

  const data = graph.data;

  return (
    <>
      <PageHeader
        title="Knowledge Graph"
        subtitle="Linked records from this platform's own data. Solid edges are declared foreign keys; dashed ones are citations resolved from report sources."
        actions={<Network size={15} className="text-muted" />}
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <label className="inline-field">
            Centre on region
            <select
              className="select"
              // The API answers with a node id ("region:20"), which matches no
              // option, so the select would silently show the first region
              // while the graph showed another. Read the centre's own code
              // out of the node instead.
              value={centreRegionCode}
              onChange={(event) =>
                setCentre({ type: "region", id: event.target.value })
              }
            >
              {centreRegionCode === "" && (
                <option value="">
                  {data?.center_type === "region" ? "Current region" : "—"}
                </option>
              )}
              {/* Stage-2 refined sub-cells are left out. They hold at most a
                  couple of records, so centring on one gives a near-empty
                  graph that reads as a bug rather than as an accurate
                  picture of a sparsely-linked cell. */}
              {zones.data?.items
                .filter((zone) => !zone.region_code.includes("__r"))
                .map((zone) => (
                  <option key={zone.region_code} value={zone.region_code}>
                    {zone.region_name}
                  </option>
                ))}
            </select>
          </label>
          <label className="inline-field">
            Depth
            <select
              className="select"
              value={depth}
              onChange={(event) => setDepth(Number(event.target.value))}
            >
              <option value={1}>1 hop</option>
              <option value={2}>2 hops</option>
            </select>
          </label>
          <span className="muted-note">
            {data?.node_count ?? 0} nodes · {data?.edge_count ?? 0} edges
            {data?.truncated ? " · truncated to fit" : ""}
          </span>
        </div>
      </SectionCard>

      <SectionCard>
        {!data || data.node_count === 0 ? (
          <p className="muted-note">No linked records.</p>
        ) : data.edge_count === 0 ? (
          <p className="muted-note">
            No linked records. This {TYPE_LABEL[data.center_type ?? ""] ?? "record"}{" "}
            exists but nothing references it and it references nothing.
          </p>
        ) : (
          <div className="kg-wrap">
            <svg
              viewBox={`${-WIDTH / 2} ${-HEIGHT / 2} ${WIDTH} ${HEIGHT}`}
              className="kg-svg"
              role="img"
              aria-label={`Graph of ${data.node_count} linked records`}
            >
              {RING.filter((r) => r > 0).map((r) => (
                <ellipse
                  key={r}
                  cx={0}
                  cy={0}
                  rx={r}
                  ry={r * 0.78}
                  className="kg-ring"
                />
              ))}

              {data.edges.map((edge) => {
                const a = positions.get(edge.source);
                const b = positions.get(edge.target);
                if (!a || !b) return null;
                const lit =
                  hovered && (hovered.id === edge.source || hovered.id === edge.target);
                const cited = edge.edge_kind === "resolved_reference";
                return (
                  <line
                    key={`${edge.source}|${edge.target}|${edge.relation}`}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    className={`kg-edge${lit ? " is-lit" : ""}${
                      cited ? " is-cited" : ""
                    }`}
                  />
                );
              })}

              {placed.map((node) => {
                const isCentre = node.id === data.center;
                const radius = isCentre ? 13 : node.depth === 1 ? 8 : 5.5;
                return (
                  <g key={node.id}>
                    <circle
                      data-node-id={node.id}
                      cx={node.x}
                      cy={node.y}
                      r={radius}
                      fill={TYPE_COLOUR[node.type] ?? "#64748b"}
                      className={`kg-node${isCentre ? " is-centre" : ""}`}
                      onMouseEnter={() => setHovered(node)}
                      onMouseLeave={() => setHovered(null)}
                      onClick={() =>
                        setCentre({
                          type: node.type,
                          id: node.id.split(":").slice(1).join(":"),
                        })
                      }
                      tabIndex={0}
                      role="button"
                      aria-label={`${TYPE_LABEL[node.type] ?? node.type}: ${node.label}`}
                    />
                    {isCentre && (
                      <text x={node.x} y={node.y - 20} className="kg-centre-label">
                        {node.label}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>

            <div className="kg-side">
              <p className="eval-heading">Legend</p>
              <ul className="kg-legend">
                {presentTypes.map((type) => (
                  <li key={type}>
                    <span
                      className="kg-dot"
                      style={{ background: TYPE_COLOUR[type] ?? "#64748b" }}
                    />
                    <span>{TYPE_LABEL[type] ?? type}</span>
                    <span className="mono">
                      {placed.filter((n) => n.type === type).length}
                    </span>
                  </li>
                ))}
              </ul>

              {(data.edge_kind_counts?.resolved_reference ?? 0) > 0 && (
                <ul className="kg-legend kg-legend-edges">
                  <li>
                    <span className="kg-line" />
                    <span>Declared foreign key</span>
                    <span className="mono">
                      {data.edge_kind_counts.foreign_key ?? 0}
                    </span>
                  </li>
                  <li>
                    <span className="kg-line is-dashed" />
                    <span>
                      Citation resolved from report sources (not a declared FK)
                    </span>
                    <span className="mono">
                      {data.edge_kind_counts.resolved_reference}
                    </span>
                  </li>
                </ul>
              )}

              <p className="muted-note">
                Pollution events and the observations behind them are{" "}
                <strong>measured</strong> — Sentinel-2 acquisitions on the
                dates shown. SAR candidates are the PANGAEA Sentinel-1
                benchmark.
              </p>

              {data.unresolved_citations > 0 && (
                <p className="muted-note">
                  {data.unresolved_citations} citation id(s) name a document
                  that is not stored, and are not drawn.
                </p>
              )}

              <div className="kg-hover">
                {hovered ? (
                  <>
                    <p className="eval-heading">
                      {TYPE_LABEL[hovered.type] ?? hovered.type}
                    </p>
                    <p className="kg-hover-label">{hovered.label}</p>
                    <div className="kv">
                      <span>Evidence</span>
                      <span className="mono">
                        {hovered.evidence_level ?? "not applicable"}
                      </span>
                    </div>
                    {Object.entries(hovered.attrs)
                      .filter(([, value]) => value !== null && value !== undefined)
                      .slice(0, 5)
                      .map(([key, value]) => (
                        <div className="kv" key={key}>
                          <span>{key.replace(/_/g, " ")}</span>
                          <span className="mono">{String(value)}</span>
                        </div>
                      ))}
                  </>
                ) : (
                  <p className="muted-note">
                    Hover a node for its evidence level. Click one to re-centre
                    the graph on it.
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="What is in the graph"
        description="Counts straight from the tables, not from a sample."
        actions={<Info size={15} className="text-muted" />}
      >
        {summary.data && (
          <>
            <div className="kg-counts">
              {Object.entries(summary.data.node_counts)
                .filter(([, n]) => n > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([type, n]) => (
                  <div className="kv" key={type}>
                    <span>
                      <span
                        className="kg-dot"
                        style={{ background: TYPE_COLOUR[type] ?? "#64748b" }}
                      />
                      {TYPE_LABEL[type] ?? type}
                    </span>
                    <span className="mono">{n.toLocaleString()}</span>
                  </div>
                ))}
            </div>
            <div className="kv">
              <strong>Total linked records</strong>
              <strong className="mono">
                {summary.data.total_nodes.toLocaleString()} nodes ·{" "}
                {summary.data.total_edges.toLocaleString()} edges
              </strong>
            </div>
            {summary.data.notes.map((note) => (
              <p className="muted-note" key={note}>
                {note}
              </p>
            ))}
          </>
        )}
      </SectionCard>
    </>
  );
}
