import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import svgr from "vite-plugin-svgr";

export default defineConfig({
  plugins: [
    // svgr MUST come before @vitejs/plugin-react so it claims .svg?react
    // imports before Vite's default asset loader turns them into URL strings.
    svgr({
      svgrOptions: { exportType: "default", ref: true },
      include: "**/*.svg?react",
    }),
    react(),
  ],
  // File:// loading in Electron production needs relative asset paths.
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    // Entry-chunk weight is managed at the source level instead of via
    // manualChunks (which this plugin combination ignores): the Firebase SDK
    // loads through dynamic import (lib/firebase.ts) and heavy pages are
    // React.lazy, so Rollup splits them automatically.
  },
  // Pre-bundle every Radix primitive + heavy dep we use so Vite never
  // re-optimizes after first paint -- that re-optimization triggers a
  // reload that Electron sees as an aborted navigation.
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-router-dom",
      "@tanstack/react-query",
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-slot",
      "@radix-ui/react-tabs",
      "@radix-ui/react-tooltip",
      "class-variance-authority",
      "clsx",
      "lucide-react",
      "tailwind-merge",
      "zustand",
    ],
  },
});
