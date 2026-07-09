import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Pencil, Search, X } from 'lucide-react'
import { txApi } from '../api'
import { usePortfolios } from '../context/PortfoliosContext'
import PortfolioSelector from '../components/PortfolioSelector'
import { PageSpinner } from '../components/Spinner'
import TransactionModal from '../components/TransactionModal'
import { fmtDate, fmtQty } from '../utils/format'

interface Instrument {
  id: number
  ticker: string
  isin: string | null
  name: string
  asset_class: string
  currency: string
  sector: string | null
  country: string | null
}

interface Transaction {
  id: number
  portfolio_id: number
  instrument_id: number
  instrument: Instrument
  type: string
  date: string
  quantity: number
  price: number
  fees: number
  currency: string
  fx_rate: number
  notes: string | null
}

export default function Transactions() {
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPf, setSelectedPf] = useState<number | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editTx, setEditTx] = useState<Transaction | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // ── Filters ───────────────────────────────────────────────────────────────
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState<'ALL' | 'BUY' | 'SELL'>('ALL')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // ── Selection ─────────────────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const selectAllRef = useRef<HTMLInputElement>(null)

  // ── Data loading ──────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await txApi.list(selectedPf ?? undefined)
      setTransactions(res.data)
      setSelectedIds(new Set())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [selectedPf])

  useEffect(() => { load() }, [load])

  // ── Filtered view ─────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return transactions.filter(tx => {
      if (filterType !== 'ALL' && tx.type !== filterType) return false
      if (dateFrom && tx.date < dateFrom) return false
      if (dateTo && tx.date > dateTo) return false
      if (search.trim()) {
        const q = search.toLowerCase()
        if (
          !tx.instrument.ticker.toLowerCase().includes(q) &&
          !tx.instrument.name.toLowerCase().includes(q)
        ) return false
      }
      return true
    })
  }, [transactions, search, filterType, dateFrom, dateTo])

  // ── Select-all logic ──────────────────────────────────────────────────────
  const visibleIds = filtered.map(t => t.id)
  const visibleSelected = visibleIds.filter(id => selectedIds.has(id))
  const allVisibleSelected = visibleIds.length > 0 && visibleSelected.length === visibleIds.length
  const someVisibleSelected = visibleSelected.length > 0 && !allVisibleSelected

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected
    }
  }, [someVisibleSelected])

  const toggleSelectAll = () => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allVisibleSelected) {
        visibleIds.forEach(id => next.delete(id))
      } else {
        visibleIds.forEach(id => next.add(id))
      }
      return next
    })
  }

  const toggleOne = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  const handleDelete = async (id: number) => {
    if (!window.confirm("Eliminare questa transazione? L'operazione non può essere annullata.")) return
    setDeletingId(id)
    try {
      await txApi.delete(id)
      setTransactions(prev => prev.filter(t => t.id !== id))
      setSelectedIds(prev => { const n = new Set(prev); n.delete(id); return n })
    } catch (e) {
      console.error(e)
      window.alert("Impossibile eliminare la transazione. Riprova.")
    } finally {
      setDeletingId(null)
    }
  }

  const handleBulkDelete = async () => {
    const n = selectedIds.size
    if (!window.confirm(`Eliminare ${n} transazion${n === 1 ? 'e' : 'i'}? L'operazione non può essere annullata.`)) return
    setBulkDeleting(true)
    try {
      const results = await Promise.allSettled([...selectedIds].map(id => txApi.delete(id)))
      const failed = results.filter(r => r.status === 'rejected').length
      setSelectedIds(new Set())
      await load()
      if (failed > 0) {
        window.alert(`${failed} transazion${failed === 1 ? 'e' : 'i'} non eliminat${failed === 1 ? 'a' : 'e'}. Riprova.`)
      }
    } finally {
      setBulkDeleting(false)
    }
  }

  const clearFilters = () => {
    setSearch(''); setFilterType('ALL'); setDateFrom(''); setDateTo('')
  }
  const hasFilters = !!(search || filterType !== 'ALL' || dateFrom || dateTo)

  // ── Helpers ───────────────────────────────────────────────────────────────
  const typeStyle = (t: string) =>
    t === 'BUY'
      ? 'bg-emerald-900/40 text-emerald-400 border border-emerald-700/30'
      : 'bg-red-900/40 text-red-400 border border-red-700/30'

  if (pfLoading) return <PageSpinner />

  return (
    <div className="space-y-4">

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Transazioni</h1>
          {!loading && (
            <p className="text-sm text-gray-500 mt-0.5">
              {filtered.length !== transactions.length
                ? `${filtered.length} di ${transactions.length} operazion${transactions.length === 1 ? 'e' : 'i'}`
                : `${transactions.length} operazion${transactions.length === 1 ? 'e' : 'i'}`}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <PortfolioSelector portfolios={portfolios} selected={selectedPf} onChange={setSelectedPf} />
          <button
            onClick={() => { setEditTx(null); setShowModal(true) }}
            className="btn-primary flex items-center gap-2 flex-shrink-0"
          >
            <Plus size={16} />
            <span>Nuova</span>
          </button>
        </div>
      </div>

      {/* ── Filter bar ───────────────────────────────────────────────────── */}
      <div className="card py-3 px-4">
        <div className="flex flex-wrap items-center gap-3">

          {/* Text search */}
          <div className="relative flex-1 min-w-[180px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
            <input
              className="input pl-8 py-1.5 text-sm"
              placeholder="Cerca ticker o nome strumento…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                <X size={13} />
              </button>
            )}
          </div>

          {/* Type pills */}
          <div className="flex gap-1 flex-shrink-0">
            {(['ALL', 'BUY', 'SELL'] as const).map(t => (
              <button
                key={t}
                type="button"
                onClick={() => setFilterType(t)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  filterType === t
                    ? t === 'BUY'
                      ? 'bg-emerald-600/25 text-emerald-400 border-emerald-500/50'
                      : t === 'SELL'
                        ? 'bg-red-600/25 text-red-400 border-red-500/50'
                        : 'bg-gold-500/15 text-gold-400 border-gold-500/30'
                    : 'bg-navy-700 text-gray-400 border-gray-600/30 hover:text-gray-200'
                }`}
              >
                {t === 'ALL' ? 'Tutti' : t}
              </button>
            ))}
          </div>

          {/* Date range */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <input
              type="date"
              className="input py-1.5 text-sm w-36"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              title="Data da"
            />
            <span className="text-gray-500 text-sm">→</span>
            <input
              type="date"
              className="input py-1.5 text-sm w-36"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
              title="Data a"
            />
          </div>

          {/* Clear */}
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 transition-colors flex-shrink-0"
            >
              <X size={13} /> Cancella filtri
            </button>
          )}
        </div>
      </div>

      {/* ── Bulk action bar ───────────────────────────────────────────────── */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-4 bg-red-900/20 border border-red-700/30 rounded-xl px-4 py-2.5">
          <span className="text-sm text-red-300 font-medium">
            {selectedIds.size} selezionat{selectedIds.size === 1 ? 'a' : 'e'}
          </span>
          <button
            onClick={handleBulkDelete}
            disabled={bulkDeleting}
            className="flex items-center gap-1.5 text-sm text-red-400 hover:text-red-300 font-semibold transition-colors disabled:opacity-40"
          >
            <Trash2 size={14} />
            {bulkDeleting ? 'Eliminazione…' : 'Elimina selezionate'}
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto text-gray-500 hover:text-gray-300 transition-colors"
            title="Deseleziona tutto"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* ── Table card ───────────────────────────────────────────────────── */}
      <div className="card">
        {loading ? (
          <PageSpinner />
        ) : transactions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="text-4xl mb-3">📋</div>
            <p className="text-gray-400 font-medium mb-1">Nessuna transazione</p>
            <p className="text-gray-600 text-sm mb-5">
              Aggiungi manualmente un'operazione o importa un file CSV dalla sezione Importa.
            </p>
            <button
              onClick={() => { setEditTx(null); setShowModal(true) }}
              className="btn-primary flex items-center gap-2"
            >
              <Plus size={16} /> Aggiungi la prima transazione
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="text-3xl mb-3">🔍</div>
            <p className="text-gray-400 font-medium">Nessuna transazione corrisponde ai filtri</p>
            <button onClick={clearFilters} className="mt-3 text-sm text-gold-500 hover:text-gold-400 transition-colors">
              Cancella filtri
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  <th className="py-2 pl-3 pr-2 w-8">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 accent-gold-500 cursor-pointer"
                    />
                  </th>
                  {['Data', 'Portafoglio', 'Strumento', 'Tipo', 'Quantità', 'Prezzo', 'Comm.', 'Totale', ''].map(h => (
                    <th
                      key={h}
                      className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap last:pr-0"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(tx => {
                  const pf = portfolios.find(p => p.id === tx.portfolio_id)
                  const total = tx.quantity * tx.price + tx.fees
                  const isSelected = selectedIds.has(tx.id)
                  return (
                    <tr
                      key={tx.id}
                      className={`border-b border-gray-700/20 last:border-0 transition-colors ${
                        isSelected ? 'bg-gold-500/5' : 'hover:bg-navy-700/30'
                      }`}
                    >
                      <td className="py-3 pl-3 pr-2">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleOne(tx.id)}
                          className="w-4 h-4 accent-gold-500 cursor-pointer"
                        />
                      </td>
                      <td className="py-3 pr-4 text-gray-400 whitespace-nowrap tabular-nums">
                        {fmtDate(tx.date)}
                      </td>
                      <td className="py-3 pr-4">
                        <span className="text-xs text-gray-500 whitespace-nowrap">{pf?.name ?? '—'}</span>
                      </td>
                      <td className="py-3 pr-4">
                        <Link to={`/instruments/${tx.instrument.id}`} className="group">
                          <div className="font-semibold text-gray-100 group-hover:text-gold-400 transition-colors break-words leading-snug max-w-[240px]" title={tx.instrument.name}>{tx.instrument.name}</div>
                          <div className="text-xs text-gray-500 font-mono mt-0.5">
                            {tx.instrument.ticker}{tx.instrument.isin ? ` · ${tx.instrument.isin}` : ''}
                          </div>
                        </Link>
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${typeStyle(tx.type)}`}>
                          {tx.type}
                        </span>
                      </td>
                      <td className="py-3 pr-4 tabular-nums text-gray-300">{fmtQty(tx.quantity)}</td>
                      <td className="py-3 pr-4 tabular-nums text-gray-300 whitespace-nowrap">
                        {tx.price.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                        <span className="text-xs text-gray-600 ml-1">{tx.currency}</span>
                      </td>
                      <td className="py-3 pr-4 tabular-nums text-gray-500">
                        {tx.fees > 0
                          ? tx.fees.toLocaleString('it-IT', { minimumFractionDigits: 2 })
                          : <span className="text-gray-700">—</span>}
                      </td>
                      <td className="py-3 pr-4 tabular-nums font-medium text-gray-200 whitespace-nowrap">
                        {total.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        <span className="text-xs text-gray-600 ml-1">{tx.currency}</span>
                      </td>
                      <td className="py-3">
                        <div className="flex items-center gap-2.5">
                          <button
                            onClick={() => { setEditTx(tx); setShowModal(true) }}
                            className="text-gray-600 hover:text-gold-400 transition-colors"
                            title="Modifica"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            onClick={() => handleDelete(tx.id)}
                            disabled={deletingId === tx.id}
                            className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40"
                            title="Elimina"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showModal && (
        <TransactionModal
          onClose={() => { setShowModal(false); setEditTx(null) }}
          onSaved={() => { setShowModal(false); setEditTx(null); load() }}
          initial={editTx ?? undefined}
        />
      )}
    </div>
  )
}
