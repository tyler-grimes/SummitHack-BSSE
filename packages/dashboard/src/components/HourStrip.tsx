import type { ForecastInterval } from '../types.ts'

interface Props {
  intervals: ForecastInterval[]
  hub: string
}

function formatHour(iso: string) {
  const d = new Date(iso)
  return `${String(d.getUTCHours()).padStart(2, '0')}:00`
}

export default function HourStrip({ intervals, hub }: Props) {
  const next6 = intervals.slice(0, 6)
  if (next6.length === 0) return null

  const maxMean = Math.max(...next6.map((iv) => iv.mean))

  return (
    <div>
      <p className="text-[#3a3a40] text-[9px] font-semibold mb-2 tracking-wide">
        NEXT 6 HOURS · {hub}
      </p>
      <div className="grid grid-cols-6 gap-3">
        {next6.map((iv, i) => {
          const spike = iv.mean >= maxMean * 0.9 && iv.mean > 45
          const rising = i === 0 || iv.mean >= next6[i - 1].mean
          return (
            <div
              key={iv.timestamp}
              className="relative bg-[#111112] border border-[#1e1e21] rounded-[10px] overflow-hidden px-4 py-3"
            >
              {spike && (
                <div className="absolute top-0 inset-x-0 h-0.5 bg-[rgba(157,124,53,0.6)]" />
              )}
              <p className="text-[#3a3a40] text-[10px]">{formatHour(iv.timestamp)}</p>
              <div className="flex items-baseline justify-between mt-2">
                <p className="text-[#f5f5f6] text-[20px] font-semibold leading-none">
                  ${Math.round(iv.mean)}
                </p>
                <span className={`text-[18px] ${spike ? 'text-[#9d7c35]' : 'text-[#3a3a40]'}`}>
                  {rising ? '↑' : '↓'}
                </span>
              </div>
              {spike && (
                <p className="text-[#9d7c35] text-[9px] mt-1">spike risk</p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
