import { useState } from 'react'
import type { AgentRun, ToolCall } from '../types.ts'

interface Props {
  runs: AgentRun[]
  running: boolean
  onRun: (mode: 'rt') => void
}

function ToolCallRow({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false)
  const statusColor = call.status === 'ok' ? '#428d5f' : '#c0392b'
  const durationStr = call.durationMs < 1000
    ? `${call.durationMs}ms`
    : `${(call.durationMs / 1000).toFixed(1)}s`

  return (
    <div className="border border-[#1e1e21] rounded-[6px] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[#161618] transition-colors"
      >
        <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: statusColor }} />
        <span className="text-[11px] font-mono text-[#f5f5f6] flex-1">{call.tool}</span>
        <span className="text-[10px] text-[#3a3a40] tabular-nums shrink-0">{durationStr}</span>
        <span className="text-[10px] text-[#3a3a40] tabular-nums shrink-0">
          {new Date(call.timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
        <span className="text-[#3a3a40] text-[10px] ml-1">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-[#1e1e21] bg-[#0d0d0e]">
          <div className="grid grid-cols-2 divide-x divide-[#1e1e21]">
            <div className="p-3">
              <p className="text-[9px] text-[#3a3a40] uppercase tracking-wide mb-1.5">Input</p>
              <pre className="text-[10px] text-[#6b6b73] font-mono whitespace-pre-wrap break-all leading-relaxed">
                {JSON.stringify(call.input, null, 2)}
              </pre>
            </div>
            <div className="p-3">
              <p className="text-[9px] text-[#3a3a40] uppercase tracking-wide mb-1.5">Output</p>
              <pre className="text-[10px] text-[#6b6b73] font-mono whitespace-pre-wrap break-all leading-relaxed max-h-[200px] overflow-y-auto">
                {JSON.stringify(call.result, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AgentPanel({ runs, running, onRun }: Props) {
  const agentRuns = runs.filter((r) => r.agent === 'OrchestratorAgent')
  const allCalls = agentRuns.flatMap((r) => r.toolCalls)
  const latestRun = agentRuns[agentRuns.length - 1] ?? null
  const callCount = allCalls.length

  return (
    <div className="bg-[#111112] border border-[#1e1e21] rounded-[10px] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e1e21]">
        <div className="flex items-center gap-3">
          <p className="text-[#3a3a40] text-[9px] font-semibold tracking-wide">ORCHESTRATOR AGENT</p>
          {callCount > 0 && (
            <span className="text-[9px] text-[#428d5f] tabular-nums">{callCount} calls</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {running && (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-[#428d5f] animate-pulse" />
              <span className="text-[#428d5f] text-[10px]">Running…</span>
            </div>
          )}
          <button
            disabled={running}
            onClick={() => onRun('rt')}
            className="px-2.5 py-1 text-[10px] border border-[#1e1e21] rounded-[4px] text-[#6b6b73] hover:text-[#f5f5f6] hover:border-[#3a3a40] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Run RT step
          </button>
        </div>
      </div>

      {/* Tool call log */}
      <div className="flex-1 overflow-y-auto p-3 space-y-1.5 min-h-[200px] max-h-[340px]">
        {allCalls.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-8 gap-2">
            <span className="text-[#3a3a40] text-[11px]">No calls yet</span>
            <span className="text-[#1e1e21] text-[10px]">Click "Run DA cycle" or "Run RT step" to see live tool calls</span>
          </div>
        ) : (
          [...allCalls].reverse().map((call) => (
            <ToolCallRow key={call.id} call={call} />
          ))
        )}
      </div>

      {/* Final output */}
      {latestRun?.finalOutput && (
        <div className="border-t border-[#1e1e21] p-3">
          <p className="text-[9px] text-[#3a3a40] uppercase tracking-wide mb-1.5">Last Output</p>
          <pre className="text-[10px] text-[#6b6b73] font-mono whitespace-pre-wrap break-all max-h-[80px] overflow-y-auto">
            {latestRun.finalOutput}
          </pre>
        </div>
      )}
    </div>
  )
}
