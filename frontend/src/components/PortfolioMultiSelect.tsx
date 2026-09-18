import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check, Layers } from 'lucide-react'
import { Portfolio } from '../context/PortfoliosContext'

interface Props {
  portfolios: Portfolio[]
  selected: number[]                 // set ESPLICITO dei portafogli spuntati
  onChange: (ids: number[]) => void
}

/**
 * Selettore portafogli multi-selezione (Dashboard). I toggle sono indipendenti:
 * cliccarne uno accende/spegne solo quello. È ammesso deselezionarli tutti, così
 * si passa da un portafoglio all'altro senza dover prima arrivare a due. "Tutti i
 * portafogli" li spunta tutti. Il default (tutti) è gestito dalla Dashboard. Il
 * PortfolioSelector single-select resta separato per le altre pagine.
 */
export default function PortfolioMultiSelect({ portfolios, selected, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const allIds = portfolios.map((p) => p.id)
  const isAll = selected.length === allIds.length && allIds.length > 0

  const toggle = (id: number) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]
    onChange(next)                                      // zero ammesso
  }

  const label = selected.length === 0
    ? 'Nessun portafoglio'
    : isAll
      ? 'Tutti i portafogli'
      : selected.length === 1
        ? (portfolios.find((p) => p.id === selected[0])?.name ?? '1 portafoglio')
        : `${selected.length} portafogli`

  // Con un solo portafoglio la multi-selezione non ha senso: etichetta statica.
  if (portfolios.length <= 1) {
    return (
      <div className="input max-w-xs text-sm flex items-center text-gray-300">
        {portfolios[0]?.name ?? 'Nessun portafoglio'}
      </div>
    )
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="input max-w-xs text-sm flex items-center justify-between gap-2 min-w-[180px]"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5 truncate">
          {!isAll && selected.length > 0 && <Layers size={14} className="text-gold-500 flex-shrink-0" />}
          <span className={`truncate ${selected.length === 0 ? 'text-amber-400' : ''}`}>{label}</span>
        </span>
        <ChevronDown size={16} className={`text-gray-400 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute right-0 z-20 mt-1 w-64 max-h-80 overflow-y-auto rounded-lg border border-gray-600/50 bg-navy-800 shadow-xl py-1"
          role="listbox"
        >
          <button
            type="button"
            onClick={() => onChange(allIds)}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-navy-700 transition-colors"
          >
            <span className={`w-4 h-4 flex items-center justify-center rounded border ${isAll ? 'bg-gold-500 border-gold-500' : 'border-gray-500'}`}>
              {isAll && <Check size={12} className="text-navy-900" />}
            </span>
            <span className={isAll ? 'text-gold-400 font-medium' : 'text-gray-200'}>Tutti i portafogli</span>
          </button>

          <div className="my-1 border-t border-gray-700/50" />

          {portfolios.map((p) => {
            const checked = selected.includes(p.id)
            return (
              <div
                key={p.id}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-navy-700 transition-colors group"
                role="option"
                aria-selected={checked}
              >
                {/* Casella: aggiunge/toglie dalla selezione multipla (non chiude) */}
                <button
                  type="button"
                  onClick={() => toggle(p.id)}
                  title={checked ? 'Togli dalla selezione' : 'Aggiungi alla selezione'}
                  className="flex-shrink-0"
                >
                  <span className={`w-4 h-4 flex items-center justify-center rounded border ${checked ? 'bg-emerald-500 border-emerald-500' : 'border-gray-500'}`}>
                    {checked && <Check size={12} className="text-navy-900" />}
                  </span>
                </button>
                {/* Nome: mostra SOLO questo portafoglio */}
                <button
                  type="button"
                  onClick={() => { onChange([p.id]); setOpen(false) }}
                  title="Mostra solo questo portafoglio"
                  className="flex-1 min-w-0 text-left truncate text-gray-200"
                >
                  {p.name}{p.broker ? <span className="text-gray-500"> — {p.broker}</span> : null}
                </button>
                <button
                  type="button"
                  onClick={() => { onChange([p.id]); setOpen(false) }}
                  className="flex-shrink-0 text-[10px] uppercase tracking-wide text-gold-500/70 hover:text-gold-400 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  Solo
                </button>
              </div>
            )
          })}

          <div className="border-t border-gray-700/50 mt-1 px-3 py-1.5 text-[10px] text-gray-500 leading-snug">
            Clicca il <span className="text-gray-400">nome</span> per vederne uno solo · la <span className="text-gray-400">casella</span> per combinarne più
          </div>
        </div>
      )}
    </div>
  )
}
