import { Kafka, type Producer, type Consumer } from "kafkajs";

const kafka = new Kafka({
  clientId: "energy-agents",
  brokers: (process.env["KAFKA_BOOTSTRAP_SERVERS"] ?? "localhost:9092").split(","),
});

export const TOPICS = {
  MARKET_EVENTS: "market.events",
  AGENT_MESSAGES: "agent.messages",
  DISPATCH_COMMANDS: "dispatch.commands",
  SETTLEMENT: "settlement.results",
} as const;

export async function createProducer(): Promise<Producer> {
  const producer = kafka.producer({ idempotent: true });
  await producer.connect();
  return producer;
}

export async function createConsumer(groupId: string, topics: string[]): Promise<Consumer> {
  const consumer = kafka.consumer({ groupId });
  await consumer.connect();
  await consumer.subscribe({ topics, fromBeginning: false });
  return consumer;
}

export async function publish(
  producer: Producer,
  topic: string,
  key: string,
  payload: unknown
): Promise<void> {
  await producer.send({
    topic,
    messages: [
      {
        key,
        value: JSON.stringify(payload),
        timestamp: Date.now().toString(),
      },
    ],
    acks: -1,
  });
}
