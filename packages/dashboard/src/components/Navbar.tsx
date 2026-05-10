import { useEffect, useState } from 'react'
import type { ServiceHealth } from '../types.ts'

function StatusDot({ status }: { status: ServiceHealth['status'] }) {
  const colorMap = {
    ok: 'bg-green-500',
    offline: 'bg-red-500',
    error: 'bg-yellow-400',
  } as const

  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${colorMap[status]}`}
      aria-label={status}
    />
  )
}

export default function Navbar() {
  const [services, setServices] = useState<ServiceHealth[]>([])

  useEffect(() => {
    async function fetchHealth() {
      try {
        const res = await fetch('/api/health')
        if (!res.ok) return
        const data = (await res.json()) as { services: ServiceHealth[] }
        setServices(data.services)
      } catch {
        // network error — leave empty
      }
    }

    void fetchHealth()
    const id = setInterval(() => void fetchHealth(), 10_000)
    return () => clearInterval(id)
  }, [])

  return (
    <nav className="sticky top-0 z-50 bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <div className="flex items-baseline gap-1.5">
          <span className="text-base font-bold text-gray-900 leading-tight">BESS</span>
          <span className="text-base font-normal text-gray-500 leading-tight">Platform</span>
        </div>

        <div className="flex items-center gap-5">
          {services.length === 0 ? (
            <span className="text-sm text-gray-400">Checking services…</span>
          ) : (
            services.map((svc) => (
              <div key={svc.name} className="flex items-center gap-2">
                <StatusDot status={svc.status} />
                <span className="text-sm text-gray-700">{svc.name}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </nav>
  )
}
