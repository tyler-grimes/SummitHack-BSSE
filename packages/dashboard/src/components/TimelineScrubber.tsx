export interface DispatchSlot {
  hour: number
  timestamp: string
  net_mw: number
  soc_mwh: number
  forecast_price: number
  forecast_revenue: number
}

interface Props {
  schedule: DispatchSlot[]
  capacityMwh: number
  hour: number | null
  onHourChange: (h: number | null) => void
}

function slotColor(slot: DispatchSlot): string {
  if (slot.net_mw > 0.1) return '#9d4545'   // discharge = sell
  if (slot.net_mw < -0.1) return '#428d5f'  // charge = buy
  return '#1e1e21'                           // hold
}

function formatTs(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
    }) + ' UTC'
  } catch { return '' }
}

export default function TimelineScrubber({ schedule, capacityMwh, hour, onHourChange }: Props) {
  const maxNet = Math.max(...schedule.map((s) => Math.abs(s.net_mw)), 1)
  const selected = hour !== null ? schedule[hour] : null

  return (
    <div className="bg-[#111112] border border-[#1e1e21] rounded-[10px] p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[#3a3a40] text-[9px] font-semibold tracking-wide">DISPATCH PLAN · 24H</p>
        <div className="flex items-center gap-3">
          {selected && (
            <span className="text-[10px] text-[#6b6b73]">
              {formatTs(selected.timestamp)} ·{' '}
              <span style={{ color: slotColor(selected) }}>
                {selected.net_mw > 0.1
                  ? `Discharge ${selected.net_mw.toFixed(0)} MW`
                  : selected.net_mw < -0.1
                  ? `Charge ${Math.abs(selected.net_mw).toFixed(0)} MW`
                  : 'Hold'}
              </span>
              {' · '}${selected.forecast_price.toFixed(2)}/MWh · SoC {Math.round(selected.soc_mwh / capacityMwh * 100)}%
              {selected.forecast_revenue > 0 && (
                <span className="text-[#9d7c35]"> · +${selected.forecast_revenue.toFixed(0)}</span>
              )}
            </span>
          )}
          {hour !== null && (
            <button
              onClick={() => onHourChange(null)}
              className="text-[9px] text-[#3a3a40] hover:text-[#6b6b73] transition-colors"
            >
              ✕ live
            </button>
          )}
        </div>
      </div>

      {/* Bar chart + scrubber */}
      <div className="relative">
        {/* Centre line */}
        <div className="absolute left-0 right-0 h-px bg-[#2a2a2e]" style={{ top: 60 }} />

        {/* Bars — discharge above centre, charge below */}
        <div className="flex gap-px" style={{ height: 120 }}>
          {schedule.map((slot, i) => {
            const isSelected = hour === i
            const frac = Math.abs(slot.net_mw) / maxNet
            const barH = slot.net_mw === 0 ? 0 : Math.max(4, Math.round(frac * 56))
            const color = slotColor(slot)
            const isDischarge = slot.net_mw > 0.1
            const isCharge = slot.net_mw < -0.1
            return (
              <div
                key={i}
                className="flex-1 flex flex-col cursor-pointer"
                style={{ height: 120 }}
                onClick={() => onHourChange(hour === i ? null : i)}
              >
                {/* top half: discharge */}
                <div className="flex-1 flex items-end pb-px">
                  {isDischarge && (
                    <div
                      className="w-full rounded-sm"
                      style={{
                        height: barH,
                        backgroundColor: color,
                        opacity: isSelected ? 1 : hour !== null ? 0.4 : 0.7,
                      }}
                    />
                  )}
                </div>
                {/* selected indicator */}
                <div
                  className="w-full"
                  style={{
                    height: 2,
                    backgroundColor: isSelected ? '#f5f5f6' : 'transparent',
                  }}
                />
                {/* bottom half: charge */}
                <div className="flex-1 flex items-start pt-px">
                  {isCharge && (
                    <div
                      className="w-full rounded-sm"
                      style={{
                        height: barH,
                        backgroundColor: color,
                        opacity: isSelected ? 1 : hour !== null ? 0.4 : 0.7,
                      }}
                    />
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Range slider — transparent overlay */}
        <input
          type="range"
          min={0}
          max={schedule.length - 1}
          value={hour ?? 0}
          onChange={(e) => onHourChange(Number(e.target.value))}
          onDoubleClick={() => onHourChange(null)}
          className="absolute inset-0 w-full opacity-0 cursor-pointer"
          style={{ height: 120 }}
        />
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-1">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-sm bg-[#9d4545]" />
          <span className="text-[9px] text-[#3a3a40]">Selling (discharge)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-sm bg-[#428d5f]" />
          <span className="text-[9px] text-[#3a3a40]">Buying (charge)</span>
        </div>
      </div>

      {/* Hour labels */}
      <div className="flex justify-between mt-1.5 px-0">
        {[0, 6, 12, 18, 23].map((h) => (
          <span key={h} className="text-[#3a3a40] text-[9px] tabular-nums">
            {String(h).padStart(2, '0')}h
          </span>
        ))}
      </div>
    </div>
  )
}
