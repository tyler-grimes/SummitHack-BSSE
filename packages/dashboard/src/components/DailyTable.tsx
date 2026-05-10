import type { DayResult } from '../types.ts'

const currencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

function formatCurrency(value: number) {
  return currencyFmt.format(value)
}

function accuracyColor(pct: number): string {
  if (pct >= 80) return 'text-green-700'
  if (pct >= 50) return 'text-yellow-600'
  return 'text-red-600'
}

function computeAccuracy(actual: number, expected: number): { label: string; pct: number | null } {
  if (expected === 0) return { label: 'N/A', pct: null }
  const pct = (actual / expected) * 100
  return { label: pct.toFixed(1) + '%', pct }
}

function StatusIndicator({ status }: { status: string }) {
  const isOk = status === 'ok' || status === 'optimal'
  const isError = status.startsWith('error')
  const dotClass = isOk
    ? 'bg-green-500'
    : isError
      ? 'bg-red-500'
      : 'bg-yellow-400'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${dotClass}`} />
      <span className="text-xs text-gray-600">{status}</span>
    </span>
  )
}

interface Props {
  days: DayResult[]
}

const TH = 'px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap'
const TD = 'px-4 py-3 text-sm text-gray-900 whitespace-nowrap'

export default function DailyTable({ days }: Props) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-xl font-bold text-gray-900 leading-tight">Daily Results</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead className="bg-gray-50 sticky top-0 z-10">
            <tr>
              <th className={TH}>Date</th>
              <th className={TH}>Expected</th>
              <th className={TH}>Actual</th>
              <th className={TH}>Accuracy</th>
              <th className={TH}>SoC Start</th>
              <th className={TH}>SoC End</th>
              <th className={TH}>Cycles</th>
              <th className={TH}>Status</th>
            </tr>
          </thead>
          <tbody>
            {days.map((day, i) => {
              const { label: accLabel, pct: accPct } = computeAccuracy(
                day.actualRevenueDollars,
                day.expectedRevenueDollars,
              )
              const rowBg = i % 2 === 0 ? 'bg-white' : 'bg-gray-50'

              return (
                <tr key={day.date} className={`${rowBg} border-b border-gray-100 last:border-0`}>
                  <td className={`${TD} font-bold`}>{day.date}</td>
                  <td className={TD}>{formatCurrency(day.expectedRevenueDollars)}</td>
                  <td className={`${TD} ${day.actualRevenueDollars < 0 ? 'text-red-600' : 'text-gray-900'}`}>
                    {formatCurrency(day.actualRevenueDollars)}
                  </td>
                  <td className={`${TD} font-bold ${accPct !== null ? accuracyColor(accPct) : 'text-gray-400'}`}>
                    {accLabel}
                  </td>
                  <td className={TD}>{(day.socStartPct * 100).toFixed(1)}%</td>
                  <td className={TD}>{(day.socEndPct * 100).toFixed(1)}%</td>
                  <td className={TD}>{day.cyclesDelta.toFixed(2)}</td>
                  <td className={TD}>
                    <StatusIndicator status={day.solverStatus} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
