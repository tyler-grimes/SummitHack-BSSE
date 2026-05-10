const NAV_ITEMS = [
  { label: 'Dashboard', anchor: null },
  { label: 'Batteries', anchor: 'batteries' },
  { label: 'Agents', anchor: 'agents' },
  { label: 'Forecasts', anchor: 'forecasts' },
]

interface Props {
  activePage: string
  onNav: (label: string, anchor: string | null) => void
}

export default function Sidebar({ activePage, onNav }: Props) {
  return (
    <aside className="flex flex-col w-[220px] min-h-screen bg-[#0d0d0e] border-r border-[#1e1e21] shrink-0">
      <div className="px-6 py-5">
        <p className="text-[#f5f5f6] text-[14px] font-bold leading-none">BESS OS</p>
        <p className="text-[#6b6b73] text-[10px] mt-1">Trading Platform</p>
      </div>

      <div className="mx-6 h-px bg-[#1e1e21]" />

      <nav className="flex-1 px-4 py-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = item.label === activePage
          return isActive ? (
            <div key={item.label} className="relative flex items-center">
              <div className="absolute left-[-16px] w-0.5 h-6 bg-[#f5f5f6] rounded-r" />
              <div className="w-full flex items-center h-8 px-3 bg-[rgba(245,245,246,0.06)] rounded-md">
                <span className="text-[#f5f5f6] text-[12px] font-semibold">{item.label}</span>
              </div>
            </div>
          ) : (
            <div
              key={item.label}
              onClick={() => onNav(item.label, item.anchor)}
              className="flex items-center h-8 px-3 rounded-md cursor-pointer hover:bg-[rgba(245,245,246,0.04)]"
            >
              <span className="text-[#6b6b73] text-[12px]">{item.label}</span>
            </div>
          )
        })}
      </nav>

      <div className="mx-6 h-px bg-[#1e1e21]" />
      <div className="flex items-center gap-2 px-6 py-4">
        <div className="w-1.5 h-1.5 rounded-full bg-[#428d5f]" />
        <span className="text-[#6b6b73] text-[10px]">ERCOT · Live</span>
      </div>
    </aside>
  )
}
