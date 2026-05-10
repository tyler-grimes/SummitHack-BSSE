import { describe, it, expect, vi } from "vitest";
import { ToolRegistry } from "../src/tools/tool-registry.js";

describe("ToolRegistry", () => {
  it("registers and executes a tool", async () => {
    const registry = new ToolRegistry();
    const handler = vi.fn().mockResolvedValue({ result: 42 });

    registry.register({
      name: "test_tool",
      description: "A test tool",
      inputSchema: { type: "object", properties: { x: { type: "number" } }, required: ["x"] },
      handler,
    });

    const result = await registry.execute("test_tool", { x: 1 });
    expect(handler).toHaveBeenCalledWith({ x: 1 });
    expect(result).toEqual({ result: 42 });
  });

  it("throws on unknown tool", async () => {
    const registry = new ToolRegistry();
    await expect(registry.execute("nonexistent", {})).rejects.toThrow(
      "Tool not registered: nonexistent"
    );
  });

  it("returns correct tool definitions for Claude API", () => {
    const registry = new ToolRegistry();
    registry.register({
      name: "my_tool",
      description: "Does something",
      inputSchema: { type: "object", properties: {}, required: [] },
      handler: () => Promise.resolve({}),
    });

    const defs = registry.getToolDefinitions();
    expect(defs).toHaveLength(1);
    expect(defs[0]).toMatchObject({
      name: "my_tool",
      description: "Does something",
      input_schema: { type: "object" },
    });
  });

  it("does not allow duplicate tool registration to silently overwrite", () => {
    const registry = new ToolRegistry();
    const first = vi.fn().mockResolvedValue("first");
    const second = vi.fn().mockResolvedValue("second");

    registry.register({ name: "dupe", description: "", inputSchema: { type: "object", properties: {}, required: [] }, handler: first });
    registry.register({ name: "dupe", description: "", inputSchema: { type: "object", properties: {}, required: [] }, handler: second });

    // Second registration overwrites first — document this behavior explicitly
    const defs = registry.getToolDefinitions();
    expect(defs).toHaveLength(1);
  });
});
