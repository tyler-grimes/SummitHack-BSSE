import { useState } from 'react'
import type { SimResult } from './types.ts'
import Navbar from './components/Navbar.tsx'
import SimulationForm from './components/SimulationForm.tsx'
import SummaryCards from './components/SummaryCards.tsx'
import SocChart from './components/SocChart.tsx'
import DailyTable from './components/DailyTable.tsx'

export default function App() {
  const [result, setResult] = useState<SimResult | null>(null)

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <SimulationForm onResult={setResult} />
        {result && (
          <>
            <SummaryCards result={result} />
            <SocChart days={result.days} />
            <DailyTable days={result.days} />
          </>
        )}
      </main>
    </div>
  )
}
