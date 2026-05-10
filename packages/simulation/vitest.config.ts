import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "simulation",
    environment: "node",
    globals: true,
    clearMocks: true,
    restoreMocks: true,
    include: ["tests/**/*.test.ts"],
  },
});
