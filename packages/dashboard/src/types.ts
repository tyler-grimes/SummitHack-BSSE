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
