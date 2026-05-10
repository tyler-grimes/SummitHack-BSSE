import type { SimResult } from '../types.ts'

const currencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

function formatCurrency(value: number) {
  return currencyFmt.format(value)
}

interface CardProps {
  label: string
  value: string
  valueClass?: string
}

function Card({ label, value, valueClass = 'text-gray-900' }: CardProps) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm flex flex-col gap-2">
      <span className="text-sm font-normal text-gray-500">{label}</span>
      <span className={`text-2xl font-bold leading-tight ${valueClass}`}>{value}</span>
    </div>
  )
}

interface Props {
  result: SimResult
}

export default function SummaryCards({ result }: Props) {
  const {
    totalExpectedRevenueDollars,
    totalActualRevenueDollars,
    totalCycles,
    daysSimulated,
  } = result

  const accuracy =
    totalExpectedRevenueDollars !== 0
      ? ((totalActualRevenueDollars / totalExpectedRevenueDollars) * 100).toFixed(1) + '%'
      : 'N/A'

  const actualClass =
    totalActualRevenueDollars >= 0 ? 'text-green-600' : 'text-red-600'
  const expectedClass =
    totalExpectedRevenueDollars >= 0 ? 'text-green-600' : 'text-red-600'

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      <Card
        label="Total Expected Revenue"
        value={formatCurrency(totalExpectedRevenueDollars)}
        valueClass={expectedClass}
      />
      <Card
        label="Total Actual Revenue"
        value={formatCurrency(totalActualRevenueDollars)}
        valueClass={actualClass}
      />
      <Card label="Forecast Accuracy" value={accuracy} />
      <Card label="Total Cycles" value={totalCycles.toFixed(2)} />
      <Card label="Days Simulated" value={String(daysSimulated)} />
    </div>
  )
}
