import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "agents",
    environment: "node",
    globals: true,
    clearMocks: true,
    restoreMocks: true,
    include: ["src/**/*.test.ts", "tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts"],
    },
  },
});
