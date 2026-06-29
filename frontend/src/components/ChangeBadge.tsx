import { fmtEur, fmtPct, pnlSign } from '../utils/format'

interface Props {
  label: string
  amount?: number | null   // EUR change (optional)
  pct: number | null       // % change
}

/**
 * Compact green/red change indicator used in chart headers, e.g.
 * "OGGI +€ 12,40 (+0,3%)" or "7GG +1,9%". Shows "—" when data is missing.
 */
export default function ChangeBadge({ label, amount, pct }: Props) {
  const has = pct != null || amount != null
  const ref = amount ?? pct ?? 0
  const color = !has
    ? 'text-gray-500'
    : ref > 0 ? 'text-emerald-400' : ref < 0 ? 'text-red-400' : 'text-gray-400'

  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
      <span className={`text-xs font-medium tabular-nums ${color}`}>
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
