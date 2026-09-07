/**
 * Application shell: brand rail, grouped navigation, header.
 *
 * The sidebar groups routes by what the user is trying to do (monitor,
 * understand, research, operate) rather than by which backend module serves
 * them, so the navigation reflects the workflow rather than the architecture.
 */

import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  Boxes,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  Gauge,
  Globe2,
  HeartPulse,
  LayoutDashboard,
  type LucideIcon,
  Menu,
  Network,
  RefreshCcw,
  Search,
  ShieldAlert,
  TrendingUp,
  Waves,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { StatusBadge, formatTime } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Command Center",
    items: [{ to: "/app/overview", label: "Overview", icon: LayoutDashboard }],
  },
  {
    title: "Monitoring",
    items: [
      { to: "/app/live", label: "Live Monitoring", icon: Activity },
      { to: "/app/events", label: "Pollution Events", icon: AlertTriangle },
      { to: "/app/map", label: "Ocean Map", icon: Globe2 },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { to: "/app/forecasts", label: "Forecasts", icon: TrendingUp },
      { to: "/app/risk", label: "Risk Analysis", icon: ShieldAlert },
      { to: "/app/knowledge-graph", label: "Knowledge Graph", icon: Network },
    ],
  },
  {
    title: "AI Research",
    items: [
      { to: "/app/research", label: "RAG Research", icon: Search },
      { to: "/app/agents", label: "Agent Analysis", icon: Bot },
      { to: "/app/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    title: "Machine Learning",
    items: [
      { to: "/app/models", label: "Model Performance", icon: Cpu },
      { to: "/app/drift", label: "Drift Monitoring", icon: Gauge },
      { to: "/app/experiments", label: "Experiments", icon: FlaskConical },
      { to: "/app/retraining", label: "Retraining", icon: RefreshCcw },
    ],
  },
  {
    title: "System",
    items: [
      { to: "/app/health", label: "System Health", icon: HeartPulse },
      { to: "/app/api", label: "API", icon: Database },
      { to: "/app/infrastructure", label: "Infrastructure", icon: Boxes },
    ],
  },
];

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <Waves size={17} strokeWidth={2.4} />
      </span>
      {!compact && (
        <span className="brand-text">
          <strong>OceanAI</strong>
          <em>Ocean Intelligence</em>
        </span>
      )}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="sidebar-nav" aria-label="Main navigation">
      {NAV_GROUPS.map((group) => (
        <div className="nav-group" key={group.title}>
          <p className="nav-group-title">{group.title}</p>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            >
              <item.icon size={15} strokeWidth={2} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

/** Live system status, derived only from the real /health response. */
function SystemStatusPill() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) return <StatusBadge tone="neutral" label="Checking…" />;
  if (isError || !data)
    return <StatusBadge tone="error" label="API unreachable" />;

  const degraded = data.components.some(
    (component) => component.name.startsWith("database") && !component.available,
  );
  return (
    <StatusBadge
      tone={degraded ? "warn" : "ok"}
      label={degraded ? "Degraded" : "System operational"}
      pulse={!degraded}
    />
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setMobileOpen(false), [location.pathname]);

  // Escape closes the drawer, for keyboard users.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 60_000,
  });

  return (
    <div className="shell">
      <aside className={`sidebar${mobileOpen ? " open" : ""}`}>
        <div className="sidebar-head">
          <Brand />
          <button
            className="icon-btn mobile-only"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <X size={17} />
          </button>
        </div>
        <Sidebar onNavigate={() => setMobileOpen(false)} />
        <div className="sidebar-foot">
          {health?.demo_mode && <span className="demo-chip">Demo mode</span>}
          <span className="version">v{health?.version ?? "—"}</span>
        </div>
      </aside>

      {mobileOpen && (
        <div
          className="scrim"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn mobile-only"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={18} />
          </button>
          <div className="topbar-title">
            <Waves size={14} className="topbar-icon" />
            <span>Ocean Intelligence Platform</span>
          </div>
          <div className="topbar-right">
            <SystemStatusPill />
            {health?.checked_at && (
              <span className="topbar-time">
                Updated {formatTime(health.checked_at)}
              </span>
            )}
          </div>
        </header>
        <main className="content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
