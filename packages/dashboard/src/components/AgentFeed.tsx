import type { AgentEvent } from '../types.ts'

const LEVEL_COLOR: Record<string, string> = {
  info: '#6b6b73',
  warning: '#9d7c35',
}

interface Props {
  events: AgentEvent[]
}

export default function AgentFeed({ events }: Props) {
  return (
    <div className="bg-[#111112] border border-[#1e1e21] rounded-[10px] overflow-hidden">
      {events.map((ev, i) => {
        const color = LEVEL_COLOR[ev.level] ?? '#6b6b73'
        return (
          <div key={i}>
            {i > 0 && <div className="mx-4 h-px bg-[#1e1e21]" />}
            <div className="flex items-center gap-3 px-4 py-2.5">
              <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
              <span
                className="text-[10px] font-medium px-2 py-0.5 rounded shrink-0"
                style={{ color, backgroundColor: `${color}24` }}
              >
                {ev.name}
              </span>
              <span className="text-[#6b6b73] text-[11px] flex-1 truncate">{ev.action}</span>
              <span className="text-[#3a3a40] text-[10px] shrink-0 tabular-nums">{ev.time}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
