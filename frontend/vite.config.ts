import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    include: ["src/test/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      thresholds: {
        lines: 95,
        statements: 95,
        branches: 90,
      },
      exclude: ["src/main.tsx", "src/types.ts", "src/test/**"],
    },
  },
});
