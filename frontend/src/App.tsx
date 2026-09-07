/**
 * Routing.
 *
 * Every page below the shell is lazily loaded so the initial bundle carries
 * only the shell and the landing page. The map and chart libraries are the
 * heaviest dependencies and are split out by the Vite config.
 */

import { Suspense, lazy } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";
import { Shell } from "./components/Shell";
import { LoadingSkeleton } from "./components/ui";

const Landing = lazy(() => import("./pages/Landing"));
const Overview = lazy(() => import("./pages/Overview"));
const LiveMonitoring = lazy(() => import("./pages/LiveMonitoring"));
const Events = lazy(() => import("./pages/Events"));
const OceanMap = lazy(() => import("./pages/OceanMap"));
const Forecasts = lazy(() => import("./pages/Forecasts"));
const RiskAnalysis = lazy(() => import("./pages/RiskAnalysis"));
const KnowledgeGraph = lazy(() => import("./pages/KnowledgeGraph"));
const Research = lazy(() => import("./pages/Research"));
const Agents = lazy(() => import("./pages/Agents"));
const Reports = lazy(() => import("./pages/Reports"));
const Models = lazy(() => import("./pages/Models"));
const Drift = lazy(() => import("./pages/Drift"));
const Experiments = lazy(() => import("./pages/Experiments"));
const Retraining = lazy(() => import("./pages/Retraining"));
const SystemHealth = lazy(() => import("./pages/SystemHealth"));
const ApiPage = lazy(() => import("./pages/ApiPage"));
const Infrastructure = lazy(() => import("./pages/Infrastructure"));

function Page({ children }: { children: React.ReactNode }) {
  return (
    <Shell>
      <Suspense fallback={<LoadingSkeleton rows={4} height={92} />}>
        {children}
      </Suspense>
    </Shell>
  );
}

const APP_ROUTES: { path: string; element: React.ReactNode }[] = [
  { path: "/app/overview", element: <Overview /> },
  { path: "/app/live", element: <LiveMonitoring /> },
  { path: "/app/events", element: <Events /> },
  { path: "/app/events/:eventId", element: <Events /> },
  { path: "/app/map", element: <OceanMap /> },
  { path: "/app/forecasts", element: <Forecasts /> },
  { path: "/app/risk", element: <RiskAnalysis /> },
  { path: "/app/risk/:eventId", element: <RiskAnalysis /> },
  { path: "/app/knowledge-graph", element: <KnowledgeGraph /> },
  { path: "/app/research", element: <Research /> },
  { path: "/app/agents", element: <Agents /> },
  { path: "/app/reports", element: <Reports /> },
  { path: "/app/reports/:reportId", element: <Reports /> },
  { path: "/app/models", element: <Models /> },
  { path: "/app/drift", element: <Drift /> },
  { path: "/app/experiments", element: <Experiments /> },
  { path: "/app/retraining", element: <Retraining /> },
  { path: "/app/health", element: <SystemHealth /> },
  { path: "/app/api", element: <ApiPage /> },
  { path: "/app/infrastructure", element: <Infrastructure /> },
];

export const router = createBrowserRouter([
  {
    path: "/app",
    element: (
      <Suspense fallback={null}>
        <Landing />
      </Suspense>
    ),
  },
  ...APP_ROUTES.map((route) => ({
    path: route.path,
    element: <Page>{route.element}</Page>,
  })),
  { path: "*", element: <Navigate to="/app" replace /> },
]);
