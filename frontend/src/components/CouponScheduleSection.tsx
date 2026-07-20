import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Plus, CalendarClock, Check, SkipForward, Trash2, RotateCcw, Loader2 } from 'lucide-react'
import { couponApi } from '../api'
import { usePortfolios } from '../context/PortfoliosContext'
import { fmtDate, fmtNum } from '../utils/format'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CouponRow {
  id: number
  instrument_id: number
  payment_date: string
  observation_date: string | null
  amount_per_unit: number
  coupon_type: 'GUARANTEED' | 'CONDITIONAL'
  memory_effect: boolean
  status: 'PLANNED' | 'PAID' | 'SKIPPED'
  dividend_event_id: number | null
  notes: string | null
}

interface Props {
  instrumentId: number
  currency: string
  /** Quantità detenuta (per il prefill del lordo alla conferma), se in posizione */
  quantity: number | null
  /** Ricarica la pagina strumento (la conferma crea un incasso tra i dividendi) */
  onChanged: () => void
}

// ── Badges ────────────────────────────────────────────────────────────────────

function typeBadge(t: CouponRow['coupon_type']) {
  return t === 'GUARANTEED'
    ? <span className="inline-block text-xs font-medium text-emerald-300 bg-emerald-900/40 border border-emerald-700/30 rounded-full px-2 py-0.5">Garantita</span>
    : <span className="inline-block text-xs font-medium text-amber-300 bg-amber-900/40 border border-amber-700/30 rounded-full px-2 py-0.5">Condizionata</span>
}

function statusBadge(s: CouponRow['status']) {
  if (s === 'PAID')    return <span className="inline-block text-xs font-medium text-emerald-400 bg-emerald-900/30 border border-emerald-700/30 rounded px-1.5 py-0.5">Pagata</span>
  if (s === 'SKIPPED') return <span className="inline-block text-xs font-medium text-red-400 bg-red-900/30 border border-red-700/30 rounded px-1.5 py-0.5">Saltata</span>
  return <span className="inline-block text-xs font-medium text-gray-300 bg-gray-700/50 border border-gray-600/30 rounded px-1.5 py-0.5">Prevista</span>
}

// ── Add-plan modal ────────────────────────────────────────────────────────────

const FREQUENCIES = [
  { key: 1,  label: 'Mensile' },
  { key: 3,  label: 'Trimestrale' },
  { key: 6,  label: 'Semestrale' },
  { key: 12, label: 'Annuale' },
] as const

function addMonths(iso: string, months: number): string {
  const d = new Date(iso + 'T00:00:00')
  const day = d.getDate()
  d.setMonth(d.getMonth() + months)
  // Fine mese: 31 gen +1 mese non deve scavallare a marzo
  if (d.getDate() !== day) d.setDate(0)
  return d.toISOString().slice(0, 10)
}

function AddCouponsModal({ instrumentId, currency, onClose, onSaved }: {
  instrumentId: number
  currency: string
  onClose: () => void
  onSaved: () => void
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [firstDate, setFirstDate]   = useState(today)
  const [frequency, setFrequency]   = useState(3)
  const [count, setCount]           = useState('4')
  const [amount, setAmount]         = useState('')
  const [couponType, setCouponType] = useState<'GUARANTEED' | 'CONDITIONAL'>('CONDITIONAL')
  const [memory, setMemory]         = useState(true)
  const [obsOffset, setObsOffset]   = useState('')   // giorni prima del pagamento (vuoto = nessuna)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  // Anteprima delle righe generate (cedole periodiche, es. trimestrali)
  const preview = useMemo(() => {
    const n = Math.min(parseInt(count) || 0, 60)
    const amt = parseFloat(amount)
    if (!firstDate || n <= 0 || !amt || amt <= 0) return []
    const off = parseInt(obsOffset)
    const rows = []
    for (let i = 0; i < n; i++) {
      const pay = addMonths(firstDate, i * frequency)
      let obs: string | null = null
      if (!isNaN(off) && off > 0) {
        const d = new Date(pay + 'T00:00:00')
        d.setDate(d.getDate() - off)
        obs = d.toISOString().slice(0, 10)
      }
      rows.push({ payment_date: pay, observation_date: obs, amount_per_unit: amt })
    }
    return rows
  }, [firstDate, frequency, count, amount, obsOffset])

  const handleSave = async () => {
    if (!preview.length) return
    setSaving(true); setError('')
    try {
      await couponApi.bulk(preview.map(r => ({
        instrument_id: instrumentId,
        payment_date: r.payment_date,
        observation_date: r.observation_date,
        amount_per_unit: r.amount_per_unit,
        coupon_type: couponType,
        memory_effect: memory,
      })))
      onSaved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore nel salvataggio')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-navy-800 border border-gray-700/50 rounded-xl w-full max-w-lg max-h-[92vh] overflow-y-auto shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/40">
          <h2 className="text-lg font-semibold text-gray-100">Aggiungi Cedole</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 transition-colors"><X size={20} /></button>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Primo pagamento</label>
              <input className="input" type="date" value={firstDate} onChange={e => setFirstDate(e.target.value)} />
            </div>
            <div>
              <label className="label">Frequenza</label>
              <select className="input" value={frequency} onChange={e => setFrequency(Number(e.target.value))}>
                {FREQUENCIES.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Numero cedole</label>
              <input className="input tabular-nums" type="number" min="1" max="60" value={count}
                onChange={e => setCount(e.target.value)} />
            </div>
            <div>
              <label className="label">Importo per unità ({currency})</label>
              <input className="input tabular-nums" type="number" min="0" step="any" placeholder="2.50"
                value={amount} onChange={e => setAmount(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Tipo</label>
              <div className="flex gap-2">
                {(['GUARANTEED', 'CONDITIONAL'] as const).map(t => (
                  <button key={t} type="button" onClick={() => setCouponType(t)}
                    className={`flex-1 py-2 rounded-lg text-xs font-semibold border transition-colors ${
                      couponType === t
                        ? t === 'GUARANTEED'
                          ? 'bg-emerald-600/25 text-emerald-400 border-emerald-500/50'
                          : 'bg-amber-600/25 text-amber-400 border-amber-500/50'
                        : 'bg-navy-700 text-gray-400 border-gray-600/40 hover:text-gray-200'
                    }`}>
                    {t === 'GUARANTEED' ? 'Garantita' : 'Condizionata'}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="label">Osservazione (gg prima)</label>
              <input className="input tabular-nums" type="number" min="0" placeholder="es. 7 — vuoto: nessuna"
                value={obsOffset} onChange={e => setObsOffset(e.target.value)} />
            </div>
          </div>

          {couponType === 'CONDITIONAL' && (
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input type="checkbox" checked={memory} onChange={e => setMemory(e.target.checked)} />
              Effetto memoria (le cedole saltate sono recuperabili)
            </label>
          )}

          {preview.length > 0 && (
            <div className="bg-navy-700/40 border border-gray-700/30 rounded-lg p-3 max-h-44 overflow-y-auto">
              <p className="text-xs text-gray-400 mb-2">{preview.length} cedole da creare:</p>
              <div className="space-y-1">
                {preview.map((r, i) => (
                  <div key={i} className="flex justify-between text-xs tabular-nums">
                    <span className="text-gray-300">{fmtDate(r.payment_date)}</span>
                    {r.observation_date && <span className="text-gray-500">oss. {fmtDate(r.observation_date)}</span>}
                    <span className="text-gray-200">{fmtNum(r.amount_per_unit, 4)} {currency}/unità</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <p className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Annulla</button>
            <button type="button" onClick={handleSave} disabled={saving || !preview.length} className="btn-primary flex-1">
              {saving ? 'Salvataggio…' : `Crea ${preview.length || ''} cedole`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Confirm modal ─────────────────────────────────────────────────────────────

function ConfirmCouponModal({ coupon, currency, quantity, onClose, onSaved }: {
  coupon: CouponRow
  currency: string
  quantity: number | null
  onClose: () => void
  onSaved: () => void
}) {
  const { portfolios } = usePortfolios()
  const [portfolioId, setPortfolioId] = useState(portfolios.length === 1 ? String(portfolios[0].id) : '')
  const suggested = quantity != null ? quantity * coupon.amount_per_unit : null
  const [gross, setGross] = useState(suggested != null ? String(Math.round(suggested * 100) / 100) : '')
  const [payDate, setPayDate] = useState(coupon.payment_date)
  const [minusComp, setMinusComp] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  const handleConfirm = async () => {
    if (!portfolioId || !gross) return
    setSaving(true); setError('')
    try {
      await couponApi.confirm(coupon.id, {
        portfolio_id: Number(portfolioId),
        gross_amount: parseFloat(gross),
        date: payDate,
        minus_compensation: minusComp,
      })
      onSaved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore nella conferma')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-navy-800 border border-gray-700/50 rounded-xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/40">
          <h2 className="text-lg font-semibold text-gray-100">Conferma Cedola Pagata</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 transition-colors"><X size={20} /></button>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-sm text-gray-400">
            Cedola del <span className="text-gray-200">{fmtDate(coupon.payment_date)}</span> —{' '}
            {fmtNum(coupon.amount_per_unit, 4)} {currency}/unità.
            Verrà registrato un incasso (come i dividendi) nel portafoglio scelto.
          </p>

          <div>
            <label className="label">Portafoglio</label>
            <select className="input" value={portfolioId} onChange={e => setPortfolioId(e.target.value)} required>
              <option value="">Seleziona portafoglio…</option>
              {portfolios.map(p => <option key={p.id} value={p.id}>{p.name}{p.broker ? ` — ${p.broker}` : ''}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Data incasso</label>
              <input className="input" type="date" value={payDate} onChange={e => setPayDate(e.target.value)} />
            </div>
            <div>
              <label className="label">Lordo totale ({currency})</label>
              <input className="input tabular-nums" type="number" min="0" step="any"
                value={gross} onChange={e => setGross(e.target.value)} />
            </div>
          </div>
          <p className="text-[11px] text-gray-500 -mt-2">
            {suggested != null && <>Suggerito: {fmtNum(suggested)} {currency} ({fmtNum(quantity!, 0)} unità × {fmtNum(coupon.amount_per_unit, 4)}). </>}
            Se questa cedola recupera cedole in memoria, indica il lordo effettivo incassato.
            {!minusComp && ' La tassazione (26%) viene stimata automaticamente.'}
          </p>

          <label className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer">
            <input type="checkbox" className="mt-0.5 accent-gold-500" checked={minusComp}
              onChange={e => setMinusComp(e.target.checked)} />
            <span>
              Compensazione minusvalenza
              <span className="block text-[11px] text-gray-500">
                L'imposta è assorbita dallo zainetto fiscale: nessuna tassa, netto = lordo.
                Modificabile anche dopo, dalla pagina Dividendi.
              </span>
            </span>
          </label>

          {error && (
            <p className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Annulla</button>
            <button type="button" onClick={handleConfirm} disabled={saving || !portfolioId || !gross} className="btn-primary flex-1">
              {saving ? 'Conferma…' : 'Conferma Pagata'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Section ───────────────────────────────────────────────────────────────────

/**
 * "Piano cedole" nella pagina strumento: calendario delle cedole (garantite vs
 * condizionate distinte visivamente), stato di ogni riga e azioni conferma/salta.
 * Solo le cedole confermate generano un incasso; le previste non toccano mai i calcoli.
 */
export default function CouponScheduleSection({ instrumentId, currency, quantity, onChanged }: Props) {
  const [coupons, setCoupons] = useState<CouponRow[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [confirming, setConfirming] = useState<CouponRow | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await couponApi.list(instrumentId)
      setCoupons(res.data ?? [])
    } catch {
      setCoupons([])
    } finally {
      setLoading(false)
    }
  }, [instrumentId])

  useEffect(() => { load() }, [load])

  const today = new Date().toISOString().slice(0, 10)
  const nextPlanned = coupons.find(c => c.status === 'PLANNED' && c.payment_date >= today)

  const handleSkip = async (c: CouponRow) => {
    setBusyId(c.id)
    try { await couponApi.skip(c.id); await load() } finally { setBusyId(null) }
  }
  const handleReset = async (c: CouponRow) => {
    setBusyId(c.id)
    try { await couponApi.reset(c.id); await load() } finally { setBusyId(null) }
  }
  const handleDelete = async (c: CouponRow) => {
    if (!window.confirm('Eliminare questa cedola dal piano?')) return
    setBusyId(c.id)
    try { await couponApi.delete(c.id); await load() } finally { setBusyId(null) }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-gray-200 flex items-center gap-2">
          <CalendarClock size={16} className="text-gold-500" />
          Piano Cedole
          {coupons.length > 0 && (
            <span className="text-sm text-gray-500 font-normal">({coupons.length})</span>
          )}
        </h2>
        <button onClick={() => setShowAdd(true)} className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5">
          <Plus size={13} /> Aggiungi cedole
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8 text-gray-500">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : coupons.length === 0 ? (
        <p className="text-gray-500 text-sm">
          Nessuna cedola pianificata. Aggiungi il piano cedolare del certificato
          (es. cedole trimestrali condizionate con effetto memoria).
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700/50">
                {['Pagamento', 'Osservazione', 'Importo/unità', 'Tipo', 'Memoria', 'Stato', ''].map((h, i) => (
                  <th key={i} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase whitespace-nowrap last:pr-0">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {coupons.map(c => {
                const isNext = nextPlanned?.id === c.id
                const isDue = c.status === 'PLANNED' && c.payment_date <= today
                return (
                  <tr key={c.id} className={`border-b border-gray-700/20 last:border-0 ${
                    isNext ? 'bg-gold-500/5' : ''
                  } ${c.status !== 'PLANNED' ? 'opacity-70' : ''}`}>
                    <td className="py-2.5 pr-4 whitespace-nowrap text-gray-300">
                      {fmtDate(c.payment_date)}
                      {isDue && <span className="ml-2 text-[10px] font-semibold text-gold-500 uppercase">in scadenza</span>}
                      {isNext && !isDue && <span className="ml-2 text-[10px] text-gold-500/70 uppercase">prossima</span>}
                    </td>
                    <td className="py-2.5 pr-4 whitespace-nowrap text-gray-500">
                      {c.observation_date ? fmtDate(c.observation_date) : '—'}
                    </td>
                    <td className="py-2.5 pr-4 tabular-nums text-gray-200">
                      {fmtNum(c.amount_per_unit, 4)} {currency}
                    </td>
                    <td className="py-2.5 pr-4">{typeBadge(c.coupon_type)}</td>
                    <td className="py-2.5 pr-4 text-gray-400">{c.memory_effect ? '✓' : '—'}</td>
                    <td className="py-2.5 pr-4">{statusBadge(c.status)}</td>
                    <td className="py-2.5 text-right whitespace-nowrap">
                      {busyId === c.id ? (
                        <Loader2 size={14} className="animate-spin inline text-gray-500" />
                      ) : c.status === 'PLANNED' ? (
                        <span className="inline-flex items-center gap-1">
                          <button onClick={() => setConfirming(c)} title="Conferma pagata"
                            className="p-1.5 rounded text-emerald-400 hover:bg-emerald-900/30 transition-colors">
                            <Check size={14} />
                          </button>
                          <button onClick={() => handleSkip(c)} title="Marca saltata"
                            className="p-1.5 rounded text-amber-400 hover:bg-amber-900/30 transition-colors">
                            <SkipForward size={14} />
                          </button>
                          <button onClick={() => handleDelete(c)} title="Elimina dal piano"
                            className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-red-900/20 transition-colors">
                            <Trash2 size={14} />
                          </button>
                        </span>
                      ) : c.status === 'SKIPPED' ? (
                        <span className="inline-flex items-center gap-1">
                          <button onClick={() => handleReset(c)} title="Riporta a prevista"
                            className="p-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-navy-700 transition-colors">
                            <RotateCcw size={14} />
                          </button>
                          <button onClick={() => handleDelete(c)} title="Elimina dal piano"
                            className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-red-900/20 transition-colors">
                            <Trash2 size={14} />
                          </button>
                        </span>
                      ) : (
                        <span className="text-[10px] text-gray-600">via Dividendi</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && (
        <AddCouponsModal
          instrumentId={instrumentId}
          currency={currency}
          onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }}
        />
      )}
      {confirming && (
        <ConfirmCouponModal
          coupon={confirming}
          currency={currency}
          quantity={quantity}
          onClose={() => setConfirming(null)}
          onSaved={() => { setConfirming(null); load(); onChanged() }}
        />
      )}
    </div>
  )
}
