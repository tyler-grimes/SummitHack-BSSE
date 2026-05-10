import { Redis } from "ioredis";

let client: Redis | null = null;

export function getRedisClient(): Redis {
  if (!client) {
    client = new Redis(
      process.env["REDIS_URL"] ?? "redis://localhost:6379",
      { lazyConnect: true, enableOfflineQueue: false }
    );
  }
  return client;
}
