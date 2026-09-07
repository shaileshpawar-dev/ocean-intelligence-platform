/**
 * Knowledge Graph.
 *
 * The backend package exists but exposes no endpoint yet, so this page shows
 * the intended entity model rather than a fabricated graph. Rendering invented
 * nodes would be exactly the kind of decoration this platform avoids.
 */

import { Link } from "react-router-dom";
import { PageHeader, NotAvailableInBackend, SectionCard } from "@/components/ui";

const PLANNED_ENTITIES = [
  "Pollution Event",
  "Region",
  "Satellite Observation",
  "Protected Area",
  "Shipping Route",
  "Environmental Regulation",
  "Risk Assessment",
];

const PLANNED_EDGES = [
  ["Pollution Event", "occurs_in", "Region"],
  ["Pollution Event", "detected_by", "Satellite Observation"],
  ["Pollution Event", "near", "Protected Area"],
  ["Pollution Event", "governed_by", "Environmental Regulation"],
  ["Pollution Event", "assessed_by", "Risk Assessment"],
];

export default function KnowledgeGraph() {
  return (
    <>
      <PageHeader
        title="Knowledge Graph"
        subtitle="Entity and relationship view over the platform's own records."
      />

      <SectionCard>
        <NotAvailableInBackend
          feature="Knowledge graph"
          reason="The backend has a knowledge_graph package reserved but exposes no endpoint yet. No graph data is fabricated here."
          alternative="The entities below already exist as real database tables and are related through foreign keys — the graph layer will project those relationships rather than invent new ones."
        />
      </SectionCard>

      <SectionCard
        title="Planned entity model"
        description="Every node type below maps to an existing table in the OceanAI schema."
      >
        <div className="kg-entities">
          {PLANNED_ENTITIES.map((entity) => (
            <span className="kg-node" key={entity}>
              {entity}
            </span>
          ))}
        </div>

        <h3 className="detail-section">Relationships</h3>
        <ul className="kg-edges">
          {PLANNED_EDGES.map(([from, relation, to]) => (
            <li key={`${from}-${relation}-${to}`}>
              <span className="kg-from">{from}</span>
              <span className="kg-rel">{relation}</span>
              <span className="kg-to">{to}</span>
            </li>
          ))}
        </ul>

        <div className="center-actions">
          <Link className="btn btn-outline btn-sm" to="/app/events">
            Browse pollution events
          </Link>
        </div>
      </SectionCard>
    </>
  );
}
