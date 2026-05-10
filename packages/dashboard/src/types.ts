export interface DayResult {
  date: string
  expectedRevenueDollars: number
  actualRevenueDollars: number
  solverStatus: string
  socStartPct: number
  socEndPct: number
  cyclesDelta: number
}

export interface SimResult {
  config: { assetId: string; iso: string; node: string; markets: string[] }
  days: DayResult[]
  totalExpectedRevenueDollars: number
  totalActualRevenueDollars: number
  totalCycles: number
  daysSimulated: number
}

export interface ServiceHealth {
  name: string
  status: 'ok' | 'offline' | 'error'
  url: string
}

export interface ForecastInterval {
  timestamp: string
  mean: number
  p10: number
  p90: number
}

export interface ForecastResponse {
  iso: string
  node: string
  market: string
  intervals: ForecastInterval[]
  model_id: string
  confidence: number
}

export type BatteryStatus = 'Charging' | 'Discharging' | 'Idle'

export interface Battery {
  id: string
  name: string
  site: string
  capacityMw: number
  capacityMwh: number
  socPct: number
  status: BatteryStatus
  powerMw: number
  pnlToday: number
}

export interface AgentEvent {
  name: string
  action: string
  time: string
  level: 'info' | 'warning'
}

export type AgentName = 'OrchestratorAgent' | 'OptimizationAgent' | 'ForecastingAgent' | 'MarketIntelAgent'

export interface ToolCall {
  id: string
  tool: string
  input: Record<string, unknown>
  result: unknown
  durationMs: number
  timestamp: string
  status: 'ok' | 'error'
}

export interface AgentRun {
  agent: AgentName
  startedAt: string
  finishedAt: string | null
  status: 'running' | 'done' | 'error'
  toolCalls: ToolCall[]
  finalOutput: string | null
}
