import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts'
import type { ForecastInterval } from '../types.ts'

const TABS = ['HB_NORTH', 'HB_SOUTH', 'HB_WEST', 'HB_HOUSTON']

interface Props {
  intervals: ForecastInterval[]
  activeHub: string
  onHubChange: (hub: string) => void
  loading: boolean
}

function formatHour(iso: string) {
  const d = new Date(iso)
  return `${String(d.getUTCHours()).padStart(2, '0')}:00`
}

export default function ForecastChart({ intervals, activeHub, onHubChange, loading }: Props) {
  const data = intervals.map((iv) => ({
    hour: formatHour(iv.timestamp),
    mean: Math.round(iv.mean * 100) / 100,
    p10: Math.round(iv.p10 * 100) / 100,
    p90: Math.round(iv.p90 * 100) / 100,
  }))

  const maxIdx = data.reduce((best, d, i) => (d.mean > (data[best]?.mean ?? 0) ? i : best), 0)
  const spikePoint = data[maxIdx]

  return (
    <div className="bg-[#111112] border border-[#1e1e21] rounded-[10px] overflow-hidden p-[18px] flex flex-col">
      {/* Hub tabs */}
      <div className="flex gap-6 mb-3">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => onHubChange(tab)}
            className={`text-[10px] pb-1.5 border-b transition-colors ${
              tab === activeHub
                ? 'text-[#f5f5f6] font-semibold border-[#f5f5f6]'
                : 'text-[#3a3a40] font-normal border-transparent hover:text-[#6b6b73]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="h-px bg-[#1e1e21] mb-3 -mx-[18px]" />

      {loading ? (
        <div className="flex-1 flex items-center justify-center h-[130px]">
          <span className="text-[#3a3a40] text-[11px]">Loading forecast…</span>
        </div>
      ) : data.length === 0 ? (
        <div className="flex-1 flex items-center justify-center h-[130px]">
          <span className="text-[#3a3a40] text-[11px]">No forecast data</span>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={130}>
          <AreaChart data={data} margin={{ top: 8, right: 36, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f5f5f6" stopOpacity={0.08} />
                <stop offset="100%" stopColor="#f5f5f6" stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid
              strokeDasharray="0"
              stroke="rgba(30,30,33,0.6)"
              horizontal
              vertical={false}
            />

            <XAxis
              dataKey="hour"
              ticks={['00:00', '06:00', '12:00', '18:00', '23:00']}
              tick={{ fontSize: 9, fill: '#3a3a40' }}
              tickLine={false}
              axisLine={false}
            />

            <YAxis
              tickFormatter={(v: number) => `$${v}`}
              tick={{ fontSize: 9, fill: '#3a3a40' }}
              tickLine={false}
              axisLine={false}
              width={28}
              tickCount={3}
            />

            <Tooltip
              contentStyle={{
                background: '#1a1a1d',
                border: '1px solid #1e1e21',
                borderRadius: 6,
                fontSize: 11,
                color: '#f5f5f6',
              }}
              formatter={(v: number) => [`$${v.toFixed(2)}`, '']}
              labelStyle={{ color: '#6b6b73', marginBottom: 4 }}
            />

            <Area
              type="monotone"
              dataKey="p90"
              stroke="none"
              fill="url(#forecastGrad)"
              fillOpacity={1}
            />
            <Area
              type="monotone"
              dataKey="mean"
              stroke="#6b6b73"
              strokeWidth={1.5}
              fill="url(#forecastGrad)"
              fillOpacity={1}
              dot={false}
              activeDot={{ r: 3, fill: '#f5f5f6', strokeWidth: 0 }}
            />

            {spikePoint && spikePoint.mean > 45 && (
              <ReferenceDot
                x={spikePoint.hour}
                y={spikePoint.mean}
                r={3}
                fill="#9d7c35"
                stroke="none"
                label={{
                  value: '↑ spike risk',
                  position: 'top',
                  fontSize: 9,
                  fill: '#9d7c35',
                  dy: -4,
                }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
