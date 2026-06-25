import { useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import { marketApi, txApi, portfolioApi } from '../api'
import { usePortfolios } from '../context/PortfoliosContext'
import TickerSearchInput, { type TickerResult } from './TickerSearchInput'

// ── Types ──────────────────────────────────────────────────────────────────────

interface InstrumentInfo {
  id?: number
  ticker: string
  isin: string | null
  name: string
  asset_class: string
  currency: string
  sector: string | null
  country: string | null
}

interface InitialTx {
  id: number
  portfolio_id: number
  instrument: InstrumentInfo
  type: string
  date: string
  quantity: number
  price: number
  fees: number
  currency: string
  fx_rate: number
  notes: string | null
}

interface Props {
  onClose: () => void
  onSaved: () => void
  initial?: InitialTx
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  Equity:        'bg-blue-900/40 text-blue-300 border-blue-700/30',
  ETF:           'bg-gold-500/15 text-gold-400 border-gold-500/25',
  'Mutual Fund': 'bg-purple-900/40 text-purple-300 border-purple-700/30',
  Bond:          'bg-teal-900/40 text-teal-300 border-teal-700/30',
}

function typeBadge(type: string) {
  const cls = TYPE_COLORS[type] ?? 'bg-gray-700/60 text-gray-400 border-gray-600/30'
  return (
    <span className={`inline-block border rounded px-1.5 py-px text-[10px] font-medium ${cls}`}>
      {type || '—'}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TransactionModal({ onClose, onSaved, initial }: Props) {
  const { portfolios, reload: reloadPortfolios } = usePortfolios()

  // ── Form state ────────────────────────────────────────────────────────────
  const [portfolioId, setPortfolioId] = useState(initial?.portfolio_id?.toString() ?? '')
  const [type, setType]   = useState<'buy' | 'sell'>(initial?.type?.toUpperCase() === 'SELL' ? 'sell' : 'buy')
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate]         = useState(initial?.date ?? today)
  const [quantity, setQuantity] = useState(initial?.quantity?.toString() ?? '')
  const [price, setPrice]       = useState(initial?.price?.toString() ?? '')
  const [fees, setFees]         = useState(initial?.fees?.toString() ?? '0')
  const [currency, setCurrency] = useState(initial?.currency ?? 'EUR')
  const [fxRate, setFxRate]     = useState(initial?.fx_rate?.toString() ?? '1')
  const [fxLoading, setFxLoading] = useState(false)
  const [fxAuto, setFxAuto]       = useState(false)
  const [notes, setNotes]       = useState(initial?.notes ?? '')

  /** Prefill the FX field with the latest stored market rate for `cur`. */
  const loadFxRate = async (cur: string) => {
    if (!cur || cur === 'EUR') { setFxRate('1'); setFxAuto(false); return }
    setFxLoading(true)
    try {
      const res = await marketApi.fxRates(cur)
      const latest = res.data?.[0]?.rate
      if (latest) { setFxRate(String(latest)); setFxAuto(true) }
    } catch {
      /* no stored rate — leave the field for manual entry */
    } finally {
      setFxLoading(false)
    }
  }

  // ── Ticker / instrument ───────────────────────────────────────────────────
  const [tickerInput, setTickerInput]     = useState(initial?.instrument?.ticker ?? '')
  const [instrument, setInstrument]       = useState<InstrumentInfo | null>(initial?.instrument ?? null)
  const [resolving, setResolving]         = useState(false)
  const [resolveError, setResolveError]   = useState('')

  // ── Inline portfolio creation ─────────────────────────────────────────────
  const [showNewPf, setShowNewPf]     = useState(false)
  const [newPfName, setNewPfName]     = useState('')
  const [newPfBroker, setNewPfBroker] = useState('')
  const [creatingPf, setCreatingPf]   = useState(false)

  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  // ── Ticker handlers ───────────────────────────────────────────────────────

  /** Called on every keystroke in the ticker input */
  const handleTickerChange = (val: string) => {
    setTickerInput(val)
    setInstrument(null)
    setResolveError('')
  }

  /** Called when user picks a result from the dropdown */
  const handleSelectTicker = async (s: TickerResult) => {
    setResolving(true)
    setResolveError('')
    try {
      const res = await marketApi.lookupInstrument({ ticker: s.ticker })
      setInstrument(res.data)
      setCurrency(res.data.currency)
      if (res.data.currency === 'EUR') { setFxRate('1'); setFxAuto(false) }
      else loadFxRate(res.data.currency)
    } catch {
      // Accept partial info so the user can still save
      setInstrument({
        ticker:      s.ticker,
        isin:        null,
        name:        s.name,
        asset_class: s.type || 'EQUITY',
        currency:    'EUR',
        sector:      null,
        country:     null,
      })
      setResolveError('Dettagli non disponibili — inserisci prezzo e valuta manualmente.')
    } finally {
      setResolving(false)
    }
  }

  // ── Portfolio creation ────────────────────────────────────────────────────

  const handleCreatePortfolio = async () => {
    if (!newPfName.trim()) return
    setCreatingPf(true)
    try {
      const res = await portfolioApi.create({ name: newPfName.trim(), broker: newPfBroker.trim() || undefined })
      await reloadPortfolios()
      setPortfolioId(String(res.data.id))
      setShowNewPf(false); setNewPfName(''); setNewPfBroker('')
    } finally {
      setCreatingPf(false)
    }
  }

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!instrument || !portfolioId) return
    setSaving(true); setError('')
    try {
      const instRes = await marketApi.createInstrument({
        ticker:      instrument.ticker,
        isin:        instrument.isin,
        name:        instrument.name,
        asset_class: instrument.asset_class,
        currency:    instrument.currency,
        sector:      instrument.sector,
        country:     instrument.country,
      })
      const payload = {
        portfolio_id:  Number(portfolioId),
        instrument_id: instRes.data.id,
        type:          type.toUpperCase(),
        date,
        quantity:  parseFloat(quantity),
        price:     parseFloat(price),
        fees:      parseFloat(fees) || 0,
        currency,
        fx_rate:   parseFloat(fxRate) || 1,
        notes:     notes.trim() || null,
      }
      if (initial?.id) await txApi.update(initial.id, payload)
      else             await txApi.create(payload)
      onSaved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore nel salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const showFx       = currency !== 'EUR'
  const controvalore = (parseFloat(quantity) || 0) * (parseFloat(price) || 0)

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-navy-800 border border-gray-700/50 rounded-xl w-full max-w-lg max-h-[92vh] overflow-y-auto shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/40">
          <h2 className="text-lg font-semibold text-gray-100">
            {initial ? 'Modifica Transazione' : 'Nuova Transazione'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 transition-colors">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">

          {/* Portfolio */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="label">Portafoglio</label>
              <button type="button" onClick={() => setShowNewPf(v => !v)}
                className="text-xs text-gold-500 hover:text-gold-400 transition-colors">
                + Nuovo portafoglio
              </button>
            </div>
            {showNewPf && (
              <div className="bg-navy-700/60 border border-gray-600/40 rounded-lg p-3 mb-2 space-y-2">
                <input className="input text-sm" placeholder="Nome *" value={newPfName} onChange={e => setNewPfName(e.target.value)} />
                <input className="input text-sm" placeholder="Broker (es. Fineco…)" value={newPfBroker} onChange={e => setNewPfBroker(e.target.value)} />
                <button type="button" onClick={handleCreatePortfolio} disabled={creatingPf || !newPfName.trim()} className="btn-primary text-sm py-1.5 w-full">
                  {creatingPf ? 'Creazione…' : 'Crea Portafoglio'}
                </button>
              </div>
            )}
            <select className="input" value={portfolioId} onChange={e => setPortfolioId(e.target.value)} required>
              <option value="">Seleziona portafoglio…</option>
              {portfolios.map(p => (
                <option key={p.id} value={p.id}>{p.name}{p.broker ? ` — ${p.broker}` : ''}</option>
              ))}
            </select>
          </div>

          {/* BUY / SELL toggle */}
          <div>
            <label className="label">Tipo operazione</label>
            <div className="flex gap-2">
              {(['buy', 'sell'] as const).map(t => (
                <button key={t} type="button" onClick={() => setType(t)}
                  className={`flex-1 py-2 rounded-lg text-sm font-semibold border transition-colors ${
                    type === t
                      ? t === 'buy'
                        ? 'bg-emerald-600/25 text-emerald-400 border-emerald-500/50'
                        : 'bg-red-600/25 text-red-400 border-red-500/50'
                      : 'bg-navy-700 text-gray-400 border-gray-600/40 hover:text-gray-200'
                  }`}>
                  {t === 'buy' ? 'Acquisto' : 'Vendita'}
                </button>
              ))}
            </div>
          </div>

          {/* Ticker search */}
          <div>
            <label className="label">Strumento</label>
            <TickerSearchInput
              value={tickerInput}
              onChange={handleTickerChange}
              onSelect={handleSelectTicker}
              placeholder="Cerca per nome o ticker (es: Apple, VWCE, BTP…)"
              inputClassName="input font-mono pr-8"
            />

            {/* Resolving spinner */}
            {resolving && (
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-400">
                <Loader2 size={12} className="animate-spin" /> Caricamento dettagli…
              </div>
            )}

            {/* Resolved instrument chip */}
            {instrument && !resolving && (
              <div className="mt-2 bg-navy-700/50 border border-gray-700/40 rounded-lg px-3 py-2 text-sm flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-gray-100">{instrument.ticker}</span>
                <span className="text-gray-400 truncate flex-1">{instrument.name}</span>
                <span className="flex-shrink-0 flex items-center gap-1.5">
                  {typeBadge(instrument.asset_class)}
                  <span className="text-xs text-gray-500">{instrument.currency}</span>
                </span>
              </div>
            )}
            {resolveError && <p className="text-amber-400 text-xs mt-1.5">{resolveError}</p>}
          </div>

          {/* Date + Quantity */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Data</label>
              <input className="input" type="date" value={date} onChange={e => setDate(e.target.value)} required />
            </div>
            <div>
              <label className="label">Quantità</label>
              <input className="input tabular-nums" type="number" min="0" step="any" placeholder="0"
                value={quantity} onChange={e => setQuantity(e.target.value)} required />
            </div>
          </div>

          {/* Price + Fees */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Prezzo ({currency})</label>
              <input className="input tabular-nums" type="number" min="0" step="any" placeholder="0.00"
                value={price} onChange={e => setPrice(e.target.value)} required />
            </div>
            <div>
              <label className="label">Commissioni ({currency})</label>
              <input className="input tabular-nums" type="number" min="0" step="any" placeholder="0.00"
                value={fees} onChange={e => setFees(e.target.value)} />
            </div>
          </div>

          {/* Currency + FX */}
          <div className={`grid gap-3 ${showFx ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <div>
              <label className="label">Valuta</label>
              <input className="input uppercase" placeholder="EUR" value={currency}
                onChange={e => {
                  const c = e.target.value.toUpperCase()
                  setCurrency(c)
                  if (c === 'EUR') { setFxRate('1'); setFxAuto(false) }
                  else if (c.length === 3) loadFxRate(c)
                }} />
            </div>
            {showFx && (
              <div>
                <label className="label">Cambio ({currency} per 1 EUR)</label>
                <input className="input tabular-nums" type="number" min="0" step="any" placeholder="1.00"
                  value={fxRate}
                  onChange={e => { setFxRate(e.target.value); setFxAuto(false) }} />
              </div>
            )}
          </div>
          {showFx && (
            fxLoading ? (
              <p className="text-xs text-gray-500 flex items-center gap-1.5">
                <Loader2 size={11} className="animate-spin" /> Recupero cambio aggiornato…
              </p>
            ) : fxAuto ? (
              <p className="text-xs text-gray-500">
                Cambio di mercato più recente — il prezzo verrà convertito in EUR. Modificalo se necessario.
              </p>
            ) : (!fxRate || parseFloat(fxRate) === 1) && (
              <p className="text-xs text-amber-400">
                Imposta il cambio {currency} per 1 EUR: con valore 1 il prezzo non viene convertito in EUR.
              </p>
            )
          )}

          {/* Notes */}
          <div>
            <label className="label">Note (opzionale)</label>
            <input className="input" placeholder="Commento libero…" value={notes} onChange={e => setNotes(e.target.value)} />
          </div>

          {/* Controvalore preview */}
          {controvalore > 0 && (
            <div className="bg-navy-700/40 border border-gray-700/30 rounded-lg px-4 py-2.5 flex items-center justify-between text-sm">
              <span className="text-gray-400">Controvalore</span>
              <span className="font-semibold text-gray-100 tabular-nums">
                {controvalore.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {currency}
                {parseFloat(fees) > 0 && (
                  <span className="text-gray-500 font-normal ml-2 text-xs">
                    + {parseFloat(fees).toLocaleString('it-IT', { minimumFractionDigits: 2 })} comm.
                  </span>
                )}
              </span>
            </div>
          )}

          {error && (
            <p className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Annulla</button>
            <button type="submit" disabled={saving || !instrument || !portfolioId} className="btn-primary flex-1">
              {saving ? 'Salvataggio…' : initial ? 'Aggiorna' : 'Salva Transazione'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
