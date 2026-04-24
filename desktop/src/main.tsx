import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import {
  MutationCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

// Self-hosted fonts (CSP forbids Google Fonts). @fontsource ships the
// weights/axes we actually use; anything else falls back via the stack in
// tailwind.config.ts.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";

import App from "./App";
import "./styles/globals.css";
import { toast } from "./lib/toast-store";

/**
 * Fallback mutation error handler. Pages that supply their own ``onError``
 * can opt out by setting ``meta: { suppressToast: true }`` on the mutation.
 * Otherwise every un-handled mutation failure fires a toast so the user
 * never sees a silent red flash and then nothing.
 */
const mutationCache = new MutationCache({
  onError: (error, _variables, _context, mutation) => {
    if (mutation.meta?.suppressToast) return;
    const message = error instanceof Error ? error.message : String(error);
    toast.error("Action failed", { description: message });
  },
});

const queryClient = new QueryClient({
  mutationCache,
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

const container = document.getElementById("root");
if (!container) throw new Error("#root not found");

// Default to dark -- the PyQt build ships light-first but the new shell is
// designed dark-first per the Phase 3 plan. Users can flip this later.
document.documentElement.classList.add("dark");

createRoot(container).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* HashRouter avoids file:// routing issues when Electron loads the
          built index.html in production. */}
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
