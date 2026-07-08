import { fmtEur, fmtPct, pnlSign } from '../utils/format'

interface Props {
  label: string
  amount?: number | null   // EUR change (optional)
  pct: number | null       // % change
  size?: 'sm' | 'lg'       // 'lg': accanto al titolo di un grafico, ben visibile
}

/**
 * Compact green/red change indicator used in chart headers, e.g.
 * "OGGI +€ 12,40 (+0,3%)" or "7GG +1,9%". Shows "—" when data is missing.
 */
export default function ChangeBadge({ label, amount, pct, size = 'sm' }: Props) {
  const has = pct != null || amount != null
  const ref = amount ?? pct ?? 0
  const color = !has
    ? 'text-gray-500'
    : ref > 0 ? 'text-emerald-400' : ref < 0 ? 'text-red-400' : 'text-gray-400'

  const labelCls = size === 'lg' ? 'text-[11px]' : 'text-[10px]'
  const valueCls = size === 'lg' ? 'text-base font-semibold' : 'text-xs font-medium'

  return (
    <span className="flex items-baseline gap-1.5">
      <span className={`${labelCls} uppercase tracking-wider text-gray-500`}>{label}</span>
      <span className={`${valueCls} tabular-nums ${color}`}>
        {!has ? '—' : (
          <>
            {amount != null && `${pnlSign(amount)}${fmtEur(amount)}`}
            {amount != null && pct != null && ' '}
            {pct != null && (amount != null ? `(${fmtPct(pct, true)})` : fmtPct(pct, true))}
          </>
        )}
      </span>
    </span>
  )
}
