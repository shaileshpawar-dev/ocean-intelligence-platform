import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { router } from "./App";
import "leaflet/dist/leaflet.css";
import "./styles/theme.css";
import "./styles/app.css";

/**
 * Query defaults tuned for a monitoring console: data is fresh for a minute,
 * and we do not refetch on every window focus, which would hammer the API
 * during a demo. Retries skip 4xx, because a 404 or a 409 "insufficient data"
 * is an answer, not a transient failure.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        const status =
          error && typeof error === "object" && "status" in error
            ? Number((error as { status: number }).status)
            : 0;
        if (status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
