import Anthropic from "@anthropic-ai/sdk";
import type { AgentID } from "@energy/shared";
import type { ToolRegistry } from "../tools/tool-registry.js";

export interface AgentConfig {
  id: AgentID;
  model: string;
  systemPrompt: string;
  maxIterations?: number;
  maxTokens?: number;
}

export abstract class BaseAgent {
  protected readonly client: Anthropic;
  protected readonly config: AgentConfig;
  protected readonly registry: ToolRegistry;

  constructor(config: AgentConfig, registry: ToolRegistry) {
    this.client = new Anthropic();
    this.config = config;
    this.registry = registry;
  }

  protected async runLoop(userMessage: string): Promise<string> {
    const messages: Anthropic.MessageParam[] = [
      { role: "user", content: userMessage },
    ];

    const maxIterations = this.config.maxIterations ?? 10;
    const tools = this.registry.getToolDefinitions();

    for (let i = 0; i < maxIterations; i++) {
      const response = await this.client.messages.create({
        model: this.config.model,
        max_tokens: this.config.maxTokens ?? 4096,
        system: this.config.systemPrompt,
        tools,
        messages,
      });

      // Append assistant turn (must include tool_use blocks for the loop to work)
      messages.push({ role: "assistant", content: response.content });

      if (response.stop_reason === "end_turn") {
        const textBlock = response.content.find(
          (b): b is Anthropic.TextBlock => b.type === "text"
        );
        return textBlock?.text ?? "";
      }

      if (response.stop_reason === "tool_use") {
        const toolResults: Anthropic.ToolResultBlockParam[] = [];

        for (const block of response.content) {
          if (block.type !== "tool_use") continue;

          const result = await this.registry.execute(block.name, block.input);
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: JSON.stringify(result),
          });
        }

        messages.push({ role: "user", content: toolResults });
        continue;
      }

      // max_tokens or stop_sequence — return what we have
      break;
    }

    throw new Error(`Agent ${this.config.id} hit max iterations (${maxIterations})`);
  }

  abstract run(input: string): Promise<string>;
}
