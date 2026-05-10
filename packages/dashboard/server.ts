import { config as loadEnv } from 'dotenv'
import { fileURLToPath } from 'node:url'
import { resolve, dirname } from 'node:path'

loadEnv({ path: resolve(dirname(fileURLToPath(import.meta.url)), '../../.env') })

import express from 'express'
import cors from 'cors'
import { runSimulation } from '../simulation/src/runner.ts'
import { DEFAULT_BATTERY } from '../simulation/src/config.ts'
import type { SimConfig } from '../simulation/src/config.ts'
import { buildRegistry } from '../agents/src/index.ts'
import { OrchestratorAgent } from '../agents/src/agents/orchestrator.ts'
import { ToolRegistry } from '../agents/src/tools/tool-registry.ts'
import { getRedisClient } from '../agents/src/redis/client.ts'

const app = express()
app.use(cors())
app.use(express.json())

const FORECASTING_URL = process.env['FORECASTING_SERVICE_URL'] ?? 'http://localhost:8001'
const OPTIMIZATION_URL = process.env['OPTIMIZATION_SERVICE_URL'] ?? 'http://localhost:8002'
const PORT = Number(process.env['API_PORT'] ?? '3001')

app.get('/api/health', async (_req, res) => {
  async function checkService(name: string, url: string) {
    try {
      const response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(3000) })
      return { name, status: response.ok ? ('ok' as const) : ('error' as const), url }
    } catch {
      return { name, status: 'offline' as const, url }
    }
  }
  const [forecasting, optimization] = await Promise.all([
    checkService('Forecast', FORECASTING_URL),
    checkService('Optimize', OPTIMIZATION_URL),
  ])
  res.json({ services: [forecasting, optimization] })
})

app.get('/api/battery/:assetId', async (req, res) => {
  try {
    const { assetId } = req.params
    const paramsRes = await fetch(`${OPTIMIZATION_URL}/battery/${assetId}`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!paramsRes.ok) throw new Error(`Optimization service: ${paramsRes.status}`)
    const params = await paramsRes.json() as { capacity_mwh: number; initial_soc_pct: number }
    const redis = getRedisClient()
    const socRaw = await redis.get(`bess:soc:${assetId}`).catch(() => null)
    const socFrac = socRaw !== null ? parseFloat(socRaw) : params.initial_soc_pct
    res.json({ assetId, socPct: Math.round(socFrac * 100), capacityMwh: params.capacity_mwh })
  } catch (err) {
    res.status(502).json({ error: err instanceof Error ? err.message : String(err) })
  }
})

app.post('/api/forecast', async (req, res) => {
  try {
    const response = await fetch(`${FORECASTING_URL}/forecast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
      signal: AbortSignal.timeout(10000),
    })
    const data = await response.json()
    res.json(data)
  } catch (err) {
    res.status(502).json({ error: err instanceof Error ? err.message : String(err) })
  }
})

app.post('/api/simulate', async (req, res) => {
  try {
    const body = req.body as {
      assetId?: string; iso?: string; node?: string; markets?: string[]
      startDate?: string; endDate?: string; basePriceMwh?: number
    }
    const config: SimConfig = {
      assetId: body.assetId ?? 'BESS-001',
      iso: body.iso ?? 'ERCOT',
      node: body.node ?? 'HB_NORTH',
      markets: body.markets ?? ['DA_ENERGY'],
      startDate: body.startDate ?? '2024-01-01',
      endDate: body.endDate ?? '2024-01-07',
      basePriceMwh: body.basePriceMwh ?? 35,
      battery: DEFAULT_BATTERY,
      forecastingUrl: FORECASTING_URL,
      optimizationUrl: OPTIMIZATION_URL,
    }
    const result = await runSimulation(config)
    res.json(result)
  } catch (err) {
    res.status(500).json({ error: err instanceof Error ? err.message : String(err) })
  }
})

/**
 * POST /api/agent/run
 * Single OrchestratorAgent with all tools. Streams tool_call/tool_result/agent_done via SSE.
 */
app.post('/api/agent/run', async (req, res) => {
  const {
    mode = 'rt',
    assetId = 'BESS-001',
    iso = 'ERCOT',
    hub = 'HB_NORTH',
    useRealPrices = false,
  } = req.body as { mode?: string; assetId?: string; iso?: string; hub?: string; useRealPrices?: boolean }

  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.flushHeaders()

  const send = (data: unknown) => res.write(`data: ${JSON.stringify(data)}\n\n`)

  try {
    const baseRegistry = buildRegistry()
    const instrumentedRegistry = new ToolRegistry()

    for (const toolDef of (baseRegistry as any).tools.values()) {
      instrumentedRegistry.register({
        ...toolDef,
        handler: async (rawInput: unknown) => {
          const input = (useRealPrices && toolDef.name === 'solve_dispatch_pulp')
            ? { ...(rawInput as Record<string, unknown>), useRawLmp: true }
            : rawInput
          const timestamp = new Date().toISOString()
          send({ type: 'tool_call', agent: 'OrchestratorAgent', tool: toolDef.name, input, timestamp })
          const t0 = Date.now()
          try {
            const result = await toolDef.handler(input)
            send({ type: 'tool_result', agent: 'OrchestratorAgent', tool: toolDef.name, result, durationMs: Date.now() - t0, status: 'ok', timestamp: new Date().toISOString() })
            return result
          } catch (err) {
            send({ type: 'tool_result', agent: 'OrchestratorAgent', tool: toolDef.name, result: { error: err instanceof Error ? err.message : String(err) }, durationMs: Date.now() - t0, status: 'error', timestamp: new Date().toISOString() })
            throw err
          }
        },
      })
    }

    send({ type: 'agent_start', agent: 'OrchestratorAgent', timestamp: new Date().toISOString() })
    const orchestrator = new OrchestratorAgent(instrumentedRegistry)
    const output = await orchestrator.runRTCycle(assetId, iso, hub)
    send({ type: 'agent_done', agent: 'OrchestratorAgent', output, timestamp: new Date().toISOString() })
  } catch (err) {
    send({ type: 'error', message: err instanceof Error ? err.message : String(err) })
  }

  res.end()
})

app.listen(PORT, () => {
  console.log(`API server listening on http://localhost:${PORT}`)
})
