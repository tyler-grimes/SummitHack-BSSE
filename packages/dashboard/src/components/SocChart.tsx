import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { DayResult } from '../types.ts'

interface Props {
  days: DayResult[]
}

interface ChartPoint {
  date: string
  socStart: number
  socEnd: number
}

export default function SocChart({ days }: Props) {
  const data: ChartPoint[] = days.map((d) => ({
    date: d.date,
    socStart: Number((d.socStartPct * 100).toFixed(1)),
    socEnd: Number((d.socEndPct * 100).toFixed(1)),
  }))

  return (
    <section className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
      <h2 className="text-xl font-bold text-gray-900 leading-tight mb-4">
        State of Charge Over Time
      </h2>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 4, right: 24, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12, fill: '#6B7280' }}
            tickLine={false}
            axisLine={{ stroke: '#E5E7EB' }}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 12, fill: '#6B7280' }}
            tickLine={false}
            axisLine={false}
            width={44}
          />
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value}%`,
              name === 'socStart' ? 'SoC Start' : 'SoC End',
            ]}
            contentStyle={{
              fontSize: 12,
              border: '1px solid #E5E7EB',
              borderRadius: 8,
              color: '#111827',
            }}
          />
          <Legend
            formatter={(value: string) => (value === 'socStart' ? 'SoC Start' : 'SoC End')}
            wrapperStyle={{ fontSize: 12, color: '#6B7280' }}
          />
          <Line
            type="monotone"
            dataKey="socStart"
            stroke="#3B82F6"
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={{ r: 3, fill: '#3B82F6' }}
            activeDot={{ r: 5 }}
          />
          <Line
            type="monotone"
            dataKey="socEnd"
            stroke="#3B82F6"
            strokeWidth={2}
            dot={{ r: 3, fill: '#3B82F6' }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  )
}
