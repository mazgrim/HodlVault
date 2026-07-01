import { X } from 'lucide-react'
import { fmtEur, fmtPct, pnlClass, pnlSign } from '../utils/format'

export interface TaxDetailRow {
  instrument_id: number
  name: string
  ticker: string
  market_value: number
  gain: number      // plus/minus non realizzata (EUR)
  rate: number      // aliquota applicata (0.26 / 0.125)
  tax: number       // imposta stimata (EUR), 0 se in perdita
}

interface Props {
  rows: TaxDetailRow[]
  onClose: () => void
}

export default function TaxDetailModal({ rows, onClose }: Props) {
  const sorted = [...rows].sort((a, b) => b.tax - a.tax)
  const totalGain = rows.reduce((s, r) => s + r.gain, 0)
  const totalTax = rows.reduce((s, r) => s + r.tax, 0)

  return (
    <div className="fixed inset-0 z-[70] bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="card border-gray-700/60 w-full max-w-2xl relative max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute top-3 right-3 text-gray-500 hover:text-gray-300">
          <X size={18} />
        </button>
        <h2 className="text-base font-semibold text-gray-200 mb-1">Dettaglio imposta sul capital gain</h2>
        <p className="text-xs text-gray-500 mb-4">
          Stima per titolo se liquidi oggi. L'imposta è applicata solo alle posizioni in plusvalenza
          (le minusvalenze non vengono compensate). 26% azioni/ETF · 12,5% titoli di Stato/obbligazioni.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700/50 text-xs text-gray-400 uppercase">
                <th className="text-left py-2 pr-4">Strumento</th>
                <th className="text-right py-2 px-3 whitespace-nowrap">Valore</th>
                <th className="text-right py-2 px-3 whitespace-nowrap">Plus/Minus</th>
                <th className="text-right py-2 px-3">Aliquota</th>
                <th className="text-right py-2 pl-3">Imposta</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.instrument_id} className="border-b border-gray-700/20">
                  <td className="py-2 pr-4">
                    <div className="text-gray-200 font-medium break-words max-w-[220px]">{r.name}</div>
                    <div className="text-xs text-gray-500 font-mono">{r.ticker}</div>
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums text-gray-300 whitespace-nowrap">{fmtEur(r.market_value)}</td>
                  <td className={`py-2 px-3 text-right tabular-nums whitespace-nowrap ${pnlClass(r.gain)}`}>
                    {pnlSign(r.gain)}{fmtEur(r.gain)}
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums text-gray-400">{r.gain > 0 ? fmtPct(r.rate * 100) : '—'}</td>
                  <td className="py-2 pl-3 text-right tabular-nums text-gray-200 whitespace-nowrap">{r.tax > 0 ? fmtEur(r.tax) : '—'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-gray-700/50 font-semibold">
                <td className="py-2 pr-4 text-gray-300">Totale</td>
                <td></td>
                <td className={`py-2 px-3 text-right tabular-nums whitespace-nowrap ${pnlClass(totalGain)}`}>
                  {pnlSign(totalGain)}{fmtEur(totalGain)}
                </td>
                <td></td>
                <td className="py-2 pl-3 text-right tabular-nums text-gold-400 whitespace-nowrap">{fmtEur(totalTax)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  )
}
