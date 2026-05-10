interface Props {
  label: string
  value: string
  sub: string
  accent?: boolean
}

export default function KpiCard({ label, value, sub, accent = false }: Props) {
  return (
    <div className="flex-1 bg-[#111112] border border-[#1e1e21] rounded-[10px] overflow-hidden px-[18px] py-[14px] flex flex-col gap-0">
      <p className="text-[#6b6b73] text-[10px]">{label}</p>
      <div className="my-2 h-px bg-[#1e1e21]" />
      <p className={`text-[22px] font-semibold leading-tight ${accent ? 'text-[#f5f5f6]' : 'text-[#f5f5f6]'}`}>
        {value}
      </p>
      <p className="text-[#3a3a40] text-[10px] mt-1.5">{sub}</p>
    </div>
  )
}
