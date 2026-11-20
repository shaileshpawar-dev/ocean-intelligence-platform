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

// India Water Intelligence. The map is the primary surface, so it is a
// top-level route rather than a tab inside a dashboard.
const IndiaWaterMap = lazy(() => import("./pages/IndiaWaterMap"));
const IndiaOverview = lazy(() => import("./pages/IndiaOverview"));
const WaterBodyDetail = lazy(() => import("./pages/WaterBodyDetail"));
const StatePage = lazy(() => import("./pages/StatePage"));
const CityPage = lazy(() => import("./pages/CityPage"));
const StationDetail = lazy(() => import("./pages/StationDetail"));
const WaterStandards = lazy(() => import("./pages/WaterStandards"));
const DataSources = lazy(() => import("./pages/DataSources"));
const WaterAI = lazy(() => import("./pages/WaterAI"));
const Overview = lazy(() => import("./pages/Overview"));
const LiveMonitoring = lazy(() => import("./pages/LiveMonitoring"));
const Events = lazy(() => import("./pages/Events"));
const OceanMap = lazy(() => import("./pages/OceanMap"));
const CandidateReview = lazy(() => import("./pages/CandidateReview"));
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
  // -- India water intelligence ---------------------------------------
  { path: "/app/india", element: <IndiaOverview /> },
  { path: "/app/water/:slug", element: <WaterBodyDetail /> },
  { path: "/app/state/:slug", element: <StatePage /> },
  { path: "/app/city/:slug", element: <CityPage /> },
  { path: "/app/stations/:stationId", element: <StationDetail /> },
  { path: "/app/standards", element: <WaterStandards /> },
  { path: "/app/data-quality", element: <DataSources /> },
  { path: "/app/ai", element: <WaterAI /> },

  // -- Marine pollution intelligence (preserved) ----------------------
  { path: "/app/overview", element: <Overview /> },
  { path: "/app/live", element: <LiveMonitoring /> },
  { path: "/app/events", element: <Events /> },
  { path: "/app/events/:eventId", element: <Events /> },
  { path: "/app/ocean-map", element: <OceanMap /> },
  { path: "/app/candidate-review", element: <CandidateReview /> },
  { path: "/app/candidate-review/:candidateId", element: <CandidateReview /> },
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
    // The map is rendered inside the shell but with the page padding
    // removed, so the geography gets the entire viewport.
    path: "/app/map",
    element: (
      <Shell fullBleed>
        <Suspense fallback={<LoadingSkeleton rows={1} height={480} />}>
          <IndiaWaterMap />
        </Suspense>
      </Shell>
    ),
  },
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
