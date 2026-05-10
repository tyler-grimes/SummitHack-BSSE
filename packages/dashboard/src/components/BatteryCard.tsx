import type { Battery } from '../types.ts'

const STATUS_COLOR: Record<string, string> = {
  Charging: '#428d5f',
  Discharging: '#9d4545',
  Idle: '#6b6b73',
}

const STATUS_LABEL: Record<string, string> = {
  Charging: '↓ Buying',
  Discharging: '↑ Selling',
  Idle: 'Idle',
}

interface Props {
  battery: Battery
}

export default function BatteryCard({ battery }: Props) {
  const color = STATUS_COLOR[battery.status] ?? '#6b6b73'
  const isActive = battery.status !== 'Idle'
  const powerStr =
    battery.status === 'Charging'
      ? `+${battery.powerMw} MW`
      : battery.status === 'Discharging'
        ? `−${Math.abs(battery.powerMw)} MW`
        : '—'

  return (
    <div
      className="bg-[#111112] rounded-[10px] overflow-hidden p-[18px] flex flex-col gap-0"
      style={{ border: isActive ? `1px solid ${color}40` : '1px solid #1e1e21' }}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[#f5f5f6] text-[13px] font-semibold">{battery.name}</p>
          <p className="text-[#6b6b73] text-[10px] mt-0.5">
            {battery.capacityMw} MW · {battery.capacityMwh} MWh
          </p>
        </div>
        {isActive && (
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />
            <span className="text-[10px] font-semibold" style={{ color }}>{STATUS_LABEL[battery.status]}</span>
          </div>
        )}
      </div>

      <div className="my-3 h-px bg-[#1e1e21]" />

      <div className="flex justify-between items-center mb-1.5">
        <p className="text-[#3a3a40] text-[9px]">SOC</p>
        <p className="text-[10px] font-semibold" style={{ color: isActive ? color : '#6b6b73' }}>
          {battery.socPct}%
        </p>
      </div>
      <div className="h-2 bg-[#1a1a1d] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${battery.socPct}%`, backgroundColor: color }}
        />
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-[8px] text-[#3a3a40]">10%</span>
        <span className="text-[8px] text-[#3a3a40]">90%</span>
      </div>

      <div className="my-2 h-px bg-[#1e1e21]" />

      <div className="flex items-center justify-between">
        <span className="text-[#3a3a40] text-[9px]">Power</span>
        <span className="text-[12px] font-semibold tabular-nums" style={{ color: isActive ? color : '#3a3a40' }}>
          {powerStr}
        </span>
      </div>

      <div className="my-2 h-px bg-[#1e1e21]" />

      <div className="flex justify-between items-center">
        <p className="text-[#3a3a40] text-[9px]">P&amp;L Today</p>
        <p className="text-[#f5f5f6] text-[12px] font-semibold">
          {battery.pnlToday >= 0 ? '+' : ''}${battery.pnlToday.toLocaleString()}
        </p>
      </div>
    </div>
  )
}
