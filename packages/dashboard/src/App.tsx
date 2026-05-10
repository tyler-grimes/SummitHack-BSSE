import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import type { Battery, ForecastInterval, ForecastResponse, AgentRun, AgentName } from './types.ts'
import TimelineScrubber from './components/TimelineScrubber.tsx'
import type { DispatchSlot } from './components/TimelineScrubber.tsx'
import Sidebar from './components/Sidebar.tsx'
import BatteryCard from './components/BatteryCard.tsx'
import ForecastChart from './components/ForecastChart.tsx'
import AgentPanel from './components/AgentPanel.tsx'

const INITIAL_BATTERIES: Battery[] = [
  {
    id: 'BESS-001',
    name: 'Battery #1',
    site: 'HB_NORTH',
    capacityMw: 100,
    capacityMwh: 400,
    socPct: 75,
    status: 'Charging',
    powerMw: 38,
    pnlToday: 2140,
  },
  {
    id: 'BESS-002',
    name: 'Battery #2',
    site: 'HB_HOUSTON',
    capacityMw: 50,
    capacityMwh: 200,
    socPct: 45,
    status: 'Discharging',
    powerMw: 28,
    pnlToday: 2140,
  },
]


function now() {
  return new Date().toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function todayStr() {
  return new Date().toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function tzStr() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone.split('/').pop()?.replace('_', ' ') ?? 'UTC'
}

const HUB_NODES: Record<string, string> = {
  HB_NORTH: 'HB_NORTH',
  HB_SOUTH: 'HB_SOUTH',
  HB_WEST: 'HB_WEST',
  HB_HOUSTON: 'HB_HOUSTON',
}

export default function App() {
  const [clock, setClock] = useState(now())
  const [activeHub, setActiveHub] = useState('HB_NORTH')
  const [forecastMap, setForecastMap] = useState<Record<string, ForecastInterval[]>>({})
  const [loadingHub, setLoadingHub] = useState<string | null>(null)
  const [asOfDate, setAsOfDate] = useState<string>('')
  const [batteries, setBatteries] = useState<Battery[]>(INITIAL_BATTERIES)
  const [playbackHour, setPlaybackHour] = useState<number | null>(null)
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([])
  const [agentRunning, setAgentRunning] = useState(false)
  const [useRealPrices, setUseRealPrices] = useState(false)
  const [activePage, setActivePage] = useState('Dashboard')
  const agentPanelRef = useRef<HTMLDivElement>(null)

  const refreshBatteries = useCallback(async () => {
    const updates = await Promise.all(
      INITIAL_BATTERIES.map(async (b) => {
        try {
          const res = await fetch(`/api/battery/${b.id}`)
          if (!res.ok) return null
          const data = await res.json() as { socPct: number }
          return { id: b.id, socPct: data.socPct }
        } catch { return null }
      })
    )
    setBatteries((prev) =>
      prev.map((b) => {
        const upd = updates.find((u) => u?.id === b.id)
        return upd ? { ...b, socPct: upd.socPct } : b
      })
    )
  }, [])

  // Poll SoC every 8s while agent is running, once after it finishes
  useEffect(() => {
    if (agentRunning) {
      const id = setInterval(refreshBatteries, 8000)
      return () => clearInterval(id)
    } else {
      refreshBatteries()
    }
  }, [agentRunning, refreshBatteries])

  // Clock tick
  useEffect(() => {
    const id = setInterval(() => setClock(now()), 1000)
    return () => clearInterval(id)
  }, [])

  const fetchForecast = useCallback(async (hub: string, dateOverride?: string) => {
    setLoadingHub(hub)
    try {
      const body: Record<string, unknown> = {
        iso: 'ERCOT',
        nodes: [HUB_NODES[hub]],
        market: 'RT_ENERGY',
        horizon_hours: 24,
      }
      const date = dateOverride !== undefined ? dateOverride : asOfDate
      if (date) body['as_of_date'] = date

      const res = await fetch('/api/forecast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error('Forecast API error')
      const data: ForecastResponse[] = await res.json()
      const intervals = data[0]?.intervals ?? []
      setForecastMap((prev) => ({ ...prev, [hub]: intervals }))
    } catch {
      setForecastMap((prev) => ({ ...prev, [hub]: [] }))
    } finally {
      setLoadingHub(null)
    }
  }, [asOfDate])

  const runAgent = useCallback((mode: 'rt') => {
    if (agentRunning) return
    setAgentRunning(true)

    // Track pending tool call start times keyed by agent+tool
    const pendingCalls: Record<string, { tool: string; input: unknown; timestamp: string }> = {}

    fetch('/api/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, assetId: 'BESS-001', iso: 'ERCOT', hub: activeHub, useRealPrices }),
    }).then(async (res) => {
      if (!res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))

            if (evt.type === 'agent_start') {
              const newRun: AgentRun = {
                agent: evt.agent as AgentName,
                startedAt: evt.timestamp,
                finishedAt: null,
                status: 'running',
                toolCalls: [],
                finalOutput: null,
              }
              setAgentRuns((prev) => [...prev, newRun])
            } else if (evt.type === 'tool_call') {
              pendingCalls[`${evt.agent}:${evt.tool}`] = { tool: evt.tool, input: evt.input, timestamp: evt.timestamp }
            } else if (evt.type === 'tool_result') {
              const key = `${evt.agent}:${evt.tool}`
              const pending = pendingCalls[key]
              if (pending) {
                const toolCall = {
                  id: crypto.randomUUID(),
                  tool: evt.tool,
                  input: pending.input as Record<string, unknown>,
                  result: evt.result,
                  durationMs: evt.durationMs,
                  timestamp: pending.timestamp,
                  status: evt.status as 'ok' | 'error',
                }
                setAgentRuns((prev) =>
                  prev.map((r) =>
                    r.agent === evt.agent && r.status === 'running'
                      ? { ...r, toolCalls: [...r.toolCalls, toolCall] }
                      : r
                  )
                )
                delete pendingCalls[key]
              }
            } else if (evt.type === 'agent_done') {
              setAgentRuns((prev) =>
                prev.map((r) =>
                  r.agent === evt.agent && r.status === 'running'
                    ? { ...r, status: 'done', finishedAt: evt.timestamp, finalOutput: evt.output }
                    : r
                )
              )
              setAgentRunning(false)
            } else if (evt.type === 'error') {
              setAgentRuns((prev) =>
                prev.map((r) =>
                  r.status === 'running'
                    ? { ...r, status: 'error', finishedAt: new Date().toISOString(), finalOutput: evt.message }
                    : r
                )
              )
              setAgentRunning(false)
            }
          } catch { /* malformed SSE line */ }
        }
      }
      setAgentRunning(false)
    }).catch(() => setAgentRunning(false))
  }, [agentRunning, activeHub])

  // Refetch all cached hubs when asOfDate changes
  const handleDateChange = useCallback((date: string) => {
    setAsOfDate(date)
    setForecastMap({})        // clear cache so all hubs refetch with new date
    fetchForecast(activeHub, date)
  }, [activeHub, fetchForecast])

  // Fetch on mount and hub change
  useEffect(() => { fetchForecast(activeHub) }, [activeHub])

  const intervals = forecastMap[activeHub] ?? []
  const loading = loadingHub === activeHub

  // Extract latest dispatch schedule from agent tool calls
  const dispatchSchedule = useMemo<DispatchSlot[] | null>(() => {
    const calls = agentRuns.flatMap((r) => r.toolCalls)
    const last = [...calls].reverse().find((c) => c.tool === 'solve_dispatch_pulp' && c.status === 'ok')
    const result = last?.result as { schedule?: DispatchSlot[] } | undefined
    return result?.schedule ?? null
  }, [agentRuns])

  // Override battery display with dispatch plan when scrubbing
  const displayBatteries = useMemo<Battery[]>(() => {
    if (playbackHour === null || !dispatchSchedule) return batteries
    const slot = dispatchSchedule[playbackHour]
    if (!slot) return batteries
    return batteries.map((b) => {
      if (b.id !== 'BESS-001') return b
      const socPct = Math.round((slot.soc_mwh / b.capacityMwh) * 100)
      const status = slot.net_mw > 0.1 ? 'Discharging' : slot.net_mw < -0.1 ? 'Charging' : 'Idle'
      const powerMw = Math.abs(slot.net_mw)
      return { ...b, socPct, status, powerMw }
    })
  }, [batteries, playbackHour, dispatchSchedule])

  return (
    <div className="flex h-screen bg-[#0a0a0b] overflow-hidden font-sans">
      <Sidebar
        activePage={activePage}
        onNav={(label, anchor) => {
          setActivePage(label)
          if (anchor === 'agents') {
            setTimeout(() => agentPanelRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
          }
        }}
      />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <div className="flex items-center px-6 py-4 border-b border-[#1e1e21] shrink-0">
          <p className="text-[#f5f5f6] text-[18px] font-semibold">Dashboard</p>
          <div className="flex items-center gap-1.5 ml-4">
            <div className={`w-1.5 h-1.5 rounded-full ${asOfDate ? 'bg-[#9d7c35]' : 'bg-[#428d5f]'}`} />
            <span className="text-[#6b6b73] text-[11px]">{asOfDate ? 'Backtest' : 'Live'}</span>
          </div>
          <div className="ml-auto flex items-center gap-3 text-[12px]">
            {/* As-of date picker — blank = live mode */}
            <div className="flex items-center gap-2">
              <span className="text-[#3a3a40] text-[10px] uppercase tracking-wide">As of</span>
              <input
                type="date"
                value={asOfDate}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => handleDateChange(e.target.value)}
                className="bg-[#1a1a1d] border border-[#1e1e21] rounded-[5px] px-2 py-1 text-[11px] text-[#6b6b73] focus:outline-none focus:border-[#3a3a40] tabular-nums"
              />
              {asOfDate && (
                <button
                  onClick={() => handleDateChange('')}
                  className="text-[10px] text-[#3a3a40] hover:text-[#6b6b73] transition-colors"
                  title="Return to live mode"
                >
                  ✕ live
                </button>
              )}
            </div>
            <div className="w-px h-4 bg-[#1e1e21]" />
            <span className="text-[#3a3a40]">{asOfDate ? `Backtest · ${asOfDate}` : todayStr()}</span>
            <span className="text-[#6b6b73] tabular-nums">{clock} {tzStr()}</span>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Batteries + Forecast */}
          <div>
            <div className="flex gap-1 mb-2">
              <p className="text-[#3a3a40] text-[9px] font-semibold tracking-wide">BATTERIES</p>
            </div>
            <div className="grid gap-4" style={{ gridTemplateColumns: '260px 260px 1fr' }}>
              {displayBatteries.map((b) => (
                <BatteryCard key={b.id} battery={b} />
              ))}
              <div>
                <p className="text-[#3a3a40] text-[9px] font-semibold tracking-wide mb-2">
                  PRICE FORECAST · 24H
                </p>
                <ForecastChart
                  intervals={intervals}
                  activeHub={activeHub}
                  onHubChange={setActiveHub}
                  loading={loading}
                />
              </div>
            </div>
          </div>

          {/* Dispatch timeline scrubber */}
          {dispatchSchedule && (
            <TimelineScrubber
              schedule={dispatchSchedule}
              capacityMwh={batteries.find((b) => b.id === 'BESS-001')?.capacityMwh ?? 400}
              hour={playbackHour}
              onHourChange={setPlaybackHour}
            />
          )}

          {/* Agent panel — real tool call log */}
          <div ref={agentPanelRef}>
            <AgentPanel
              runs={agentRuns}
              running={agentRunning}
              onRun={runAgent}
            />
          </div>

          {/* Bottom bar: real prices toggle */}
          <div className="flex items-center gap-3 py-2">
            <button
              onClick={() => setUseRealPrices((v) => !v)}
              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 transition-colors duration-200 ${
                useRealPrices ? 'bg-[#428d5f] border-[#428d5f]' : 'bg-[#1e1e21] border-[#1e1e21]'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 mt-px rounded-full bg-[#f5f5f6] shadow transition-transform duration-200 ${
                  useRealPrices ? 'translate-x-3.5' : 'translate-x-0'
                }`}
              />
            </button>
            <span className="text-[10px] text-[#6b6b73]">
              {useRealPrices
                ? 'Real prices (DB/historical shape) — LP sees actual market spread'
                : 'ML forecast prices — smoother, less spread'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
