import { useState, type FormEvent } from 'react'
import type { SimResult } from '../types.ts'

const MARKET_OPTIONS = ['DA_ENERGY', 'RT_ENERGY', 'REG_UP', 'REG_DOWN'] as const

interface FormState {
  assetId: string
  iso: string
  node: string
  startDate: string
  endDate: string
  basePriceMwh: string
  markets: string[]
}

interface Props {
  onResult: (result: SimResult) => void
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4 text-white"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

const INPUT_BASE =
  'w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-400 ' +
  'focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition'

export default function SimulationForm({ onResult }: Props) {
  const [form, setForm] = useState<FormState>({
    assetId: 'BESS-001',
    iso: 'ERCOT',
    node: 'HB_NORTH',
    startDate: '2024-01-01',
    endDate: '2024-01-07',
    basePriceMwh: '35',
    markets: ['DA_ENERGY'],
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleChange(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
    setError(null)
  }

  function toggleMarket(market: string) {
    setForm((prev) => {
      const has = prev.markets.includes(market)
      return {
        ...prev,
        markets: has ? prev.markets.filter((m) => m !== market) : [...prev.markets, market],
      }
    })
    setError(null)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (form.markets.length === 0) {
      setError('Select at least one market.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          assetId: form.assetId,
          iso: form.iso,
          node: form.node,
          startDate: form.startDate,
          endDate: form.endDate,
          basePriceMwh: Number(form.basePriceMwh),
          markets: form.markets,
        }),
      })
      if (!res.ok) {
        const body = (await res.json()) as { error?: string }
        throw new Error(body.error ?? `Server error ${res.status}`)
      }
      const data = (await res.json()) as SimResult
      onResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
      <h2 className="text-xl font-bold text-gray-900 leading-tight mb-6">Simulation Configuration</h2>

      <form onSubmit={(e) => void handleSubmit(e)} noValidate>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          {/* Asset ID */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="assetId">
              Asset ID
            </label>
            <input
              id="assetId"
              type="text"
              className={INPUT_BASE}
              value={form.assetId}
              onChange={(e) => handleChange('assetId', e.target.value)}
              required
            />
          </div>

          {/* ISO */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="iso">
              ISO
            </label>
            <select
              id="iso"
              className={INPUT_BASE}
              value={form.iso}
              onChange={(e) => handleChange('iso', e.target.value)}
            >
              <option value="ERCOT">ERCOT</option>
              <option value="PJM">PJM</option>
            </select>
          </div>

          {/* Node */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="node">
              Node
            </label>
            <input
              id="node"
              type="text"
              className={INPUT_BASE}
              value={form.node}
              onChange={(e) => handleChange('node', e.target.value)}
              required
            />
          </div>

          {/* Start Date */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="startDate">
              Start Date
            </label>
            <input
              id="startDate"
              type="date"
              className={INPUT_BASE}
              value={form.startDate}
              onChange={(e) => handleChange('startDate', e.target.value)}
              required
            />
          </div>

          {/* End Date */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="endDate">
              End Date
            </label>
            <input
              id="endDate"
              type="date"
              className={INPUT_BASE}
              value={form.endDate}
              onChange={(e) => handleChange('endDate', e.target.value)}
              required
            />
          </div>

          {/* Base Price */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-bold text-gray-700" htmlFor="basePriceMwh">
              Base Price $/MWh
            </label>
            <input
              id="basePriceMwh"
              type="number"
              min="0"
              step="0.01"
              className={INPUT_BASE}
              value={form.basePriceMwh}
              onChange={(e) => handleChange('basePriceMwh', e.target.value)}
              required
            />
          </div>
        </div>

        {/* Markets */}
        <div className="mb-6">
          <fieldset>
            <legend className="text-sm font-bold text-gray-700 mb-2">Markets</legend>
            <div className="flex flex-wrap gap-4">
              {MARKET_OPTIONS.map((market) => (
                <label key={market} className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-200"
                    checked={form.markets.includes(market)}
                    onChange={() => toggleMarket(market)}
                  />
                  <span className="text-sm text-gray-900">{market}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        {error && (
          <p className="mb-4 text-sm text-red-600 border border-red-200 bg-red-50 rounded-md px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="inline-flex items-center gap-2 px-6 py-2.5 bg-blue-500 hover:bg-blue-600 text-white text-sm font-bold rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading && <Spinner />}
          {loading ? 'Running…' : 'Run Simulation'}
        </button>
      </form>
    </section>
  )
}
