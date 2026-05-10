import express from 'express'
import cors from 'cors'
import { runSimulation } from '../simulation/src/runner.js'
import { DEFAULT_BATTERY } from '../simulation/src/config.js'
import type { SimConfig } from '../simulation/src/config.js'

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

app.post('/api/simulate', async (req, res) => {
  try {
    const body = req.body as {
      assetId?: string
      iso?: string
      node?: string
      markets?: string[]
      startDate?: string
      endDate?: string
      basePriceMwh?: number
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

app.listen(PORT, () => {
  console.log(`API server listening on http://localhost:${PORT}`)
})
