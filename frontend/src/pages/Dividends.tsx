import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import PortfolioSelector from '../components/PortfolioSelector'
import KpiCard from '../components/KpiCard'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { divApi } from '../api'
import { fmtEur, fmtPct, fmtDate, fmtMonth } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'
import { Landmark, TrendingUp, Calendar, Search, X, Trash2 } from 'lucide-react'

interface DividendEvent {
  id: number; instrument_id: number; date: string; amount: number; currency: string; fx_rate: number
  type: string; instrument: { ticker: string; name: string; isin: string | null }
}
interface MonthlyDiv { month: string; amount: number }
interface DivProjection { month: string; amount: number }
interface KPIs { total_ytd: number; total_all_time: number; avg_yield_on_cost: number }

export default function Dividends() {
  const { tooltip, neutralSeries, barCursor } = useChartTheme()
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPf, setSelectedPf] = useState<number | null>(null)
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [monthly, setMonthly] = useState<MonthlyDiv[]>([])
  const [projection, setProjection] = useState<DivProjection[]>([])
  const [kpis, setKpis] = useState<KPIs | null>(null)
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // ── Filters ───────────────────────────────────────────────────────────────
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('ALL')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // ── Selection ─────────────────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const selectAllRef = useRef<HTMLInputElement>(null)

  // ── Load ──────────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [evRes, kRes, mRes, pRes] = await Promise.all([
        divApi.list(selectedPf ?? undefined),
        divApi.kpis(selectedPf ?? undefined),
        divApi.monthly(selectedPf ?? undefined),
        divApi.projection(selectedPf ?? undefined),
      ])
      setEvents(evRes.data)
      setKpis(kRes.data)
      setMonthly(mRes.data)
      setProjection(pRes.data)
      setSelectedIds(new Set())
    } finally {
      setLoading(false)
    }
  }, [selectedPf])

  useEffect(() => { load() }, [load])

  // ── Derived event types (for type filter pills) ───────────────────────────
  const eventTypes = useMemo(() => {
    const types = new Set(events.map(e => e.type))
    return ['ALL', ...Array.from(types).sort()]
  }, [events])

  // ── Filtered rows ─────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return events.filter(ev => {
      if (filterType !== 'ALL' && ev.type !== filterType) return false
      if (dateFrom && ev.date < dateFrom) return false
      if (dateTo && ev.date > dateTo) return false
      if (search.trim()) {
        const q = search.toLowerCase()
        if (
          !ev.instrument.ticker.toLowerCase().includes(q) &&
          !ev.instrument.name.toLowerCase().includes(q)
        ) return false
      }
      return true
    })
  }, [events, search, filterType, dateFrom, dateTo])

  // ── Select-all logic ──────────────────────────────────────────────────────
  const visibleIds = filtered.map(e => e.id)
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
    if (!window.confirm("Eliminare questo dividendo? L'operazione non può essere annullata.")) return
    setDeletingId(id)
    try {
      await divApi.delete(id)
      setEvents(prev => prev.filter(e => e.id !== id))
      setSelectedIds(prev => { const n = new Set(prev); n.delete(id); return n })
    } finally {
      setDeletingId(null)
    }
  }

  const handleBulkDelete = async () => {
    const n = selectedIds.size
    if (!window.confirm(`Eliminare ${n} dividend${n === 1 ? 'o' : 'i'}? L'operazione non può essere annullata.`)) return
    setBulkDeleting(true)
    try {
      await Promise.all([...selectedIds].map(id => divApi.delete(id)))
      setSelectedIds(new Set())
      await load()
    } finally {
      setBulkDeleting(false)
    }
  }

  const clearFilters = () => {
    setSearch(''); setFilterType('ALL'); setDateFrom(''); setDateTo('')
  }
  const hasFilters = !!(search || filterType !== 'ALL' || dateFrom || dateTo)

  if (pfLoading) return <PageSpinner />

  const barData  = monthly.map(m => ({ month: fmtMonth(m.month), importo: m.amount }))
  const projData = projection.map(p => ({ month: fmtMonth(p.month), importo: p.amount }))

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100">Dividendi &amp; Cedole</h1>
        <PortfolioSelector portfolios={portfolios} selected={selectedPf} onChange={setSelectedPf} />
      </div>

      {loading ? <PageSpinner /> : (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <KpiCard title="Totale YTD"         value={fmtEur(kpis?.total_ytd ?? 0)}          icon={<Landmark size={16} />} gold />
            <KpiCard title="Totale Storico"      value={fmtEur(kpis?.total_all_time ?? 0)}     icon={<TrendingUp size={16} />} />
            <KpiCard title="Yield on Cost Medio" value={fmtPct(kpis?.avg_yield_on_cost ?? 0)} icon={<Calendar size={16} />} />
          </div>

          {/* Monthly bar chart */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Dividendi Ultimi 12 Mesi</h2>
            {barData.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
                Nessun dividendo registrato
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis tickFormatter={v => `€${v}`} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v: number) => [fmtEur(v), 'Importo']}
                    contentStyle={tooltip()}
                    cursor={barCursor}
                  />
                  <Bar dataKey="importo" fill="#D4A017" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Projection */}
          {projData.length > 0 && (
            <div className="card">
              <h2 className="text-base font-semibold text-gray-200 mb-4">Proiezione Prossimi 12 Mesi</h2>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={projData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis tickFormatter={v => `€${v}`} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v: number) => [fmtEur(v), 'Proiezione']}
                    contentStyle={tooltip()}
                    cursor={barCursor}
                  />
                  <Bar dataKey="importo" fill={neutralSeries} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── Storico Incassi ────────────────────────────────────────────── */}
          <div className="card space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-200">Storico Incassi</h2>
              {!loading && (
                <span className="text-xs text-gray-500">
                  {filtered.length !== events.length
                    ? `${filtered.length} di ${events.length}`
                    : `${events.length} event${events.length === 1 ? 'o' : 'i'}`}
                </span>
              )}
            </div>

            {events.length > 0 && (
              <>
                {/* Filter bar */}
                <div className="flex flex-wrap items-center gap-3">

                  {/* Text search */}
                  <div className="relative flex-1 min-w-[160px]">
                    <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
                    <input
                      className="input pl-8 py-1.5 text-sm"
                      placeholder="Cerca ticker o nome…"
                      value={search}
                      onChange={e => setSearch(e.target.value)}
                    />
                    {search && (
                      <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                        <X size={13} />
                      </button>
                    )}
                  </div>

                  {/* Type pills (dynamic based on data) */}
                  <div className="flex gap-1 flex-shrink-0 flex-wrap">
                    {eventTypes.map(t => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setFilterType(t)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                          filterType === t
                            ? 'bg-gold-500/15 text-gold-400 border-gold-500/30'
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

                  {hasFilters && (
                    <button
                      onClick={clearFilters}
                      className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 transition-colors flex-shrink-0"
                    >
                      <X size={13} /> Cancella filtri
                    </button>
                  )}
                </div>

                {/* Bulk action bar */}
                {selectedIds.size > 0 && (
                  <div className="flex items-center gap-4 bg-red-900/20 border border-red-700/30 rounded-xl px-4 py-2.5">
                    <span className="text-sm text-red-300 font-medium">
                      {selectedIds.size} selezionat{selectedIds.size === 1 ? 'o' : 'i'}
                    </span>
                    <button
                      onClick={handleBulkDelete}
                      disabled={bulkDeleting}
                      className="flex items-center gap-1.5 text-sm text-red-400 hover:text-red-300 font-semibold transition-colors disabled:opacity-40"
                    >
                      <Trash2 size={14} />
                      {bulkDeleting ? 'Eliminazione…' : 'Elimina selezionati'}
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
              </>
            )}

            {/* Table */}
            {events.length === 0 ? (
              <p className="text-gray-500 text-sm">Nessun dividendo registrato.</p>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="text-2xl mb-2">🔍</div>
                <p className="text-gray-400 text-sm">Nessun dividendo corrisponde ai filtri</p>
                <button onClick={clearFilters} className="mt-2 text-xs text-gold-500 hover:text-gold-400 transition-colors">
                  Cancella filtri
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700/50">
                      <th className="py-2 pl-1 pr-2 w-8">
                        <input
                          ref={selectAllRef}
                          type="checkbox"
                          checked={allVisibleSelected}
                          onChange={toggleSelectAll}
                          className="w-4 h-4 accent-gold-500 cursor-pointer"
                        />
                      </th>
                      {['Data', 'Strumento', 'Tipo', 'Importo', 'Valuta', 'Importo EUR', ''].map(h => (
                        <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase last:pr-0">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(ev => {
                      const isSelected = selectedIds.has(ev.id)
                      return (
                        <tr
                          key={ev.id}
                          className={`border-b border-gray-700/20 last:border-0 transition-colors ${
                            isSelected ? 'bg-gold-500/5' : 'hover:bg-navy-700/30'
                          }`}
                        >
                          <td className="py-2.5 pl-1 pr-2">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleOne(ev.id)}
                              className="w-4 h-4 accent-gold-500 cursor-pointer"
                            />
                          </td>
                          <td className="py-2.5 pr-4 text-gray-300 whitespace-nowrap">{fmtDate(ev.date)}</td>
                          <td className="py-2.5 pr-4">
                            <Link to={`/instruments/${ev.instrument_id}`} className="group">
                              <div className="font-medium text-gray-100 group-hover:text-gold-400 transition-colors truncate max-w-[200px]">{ev.instrument.name}</div>
                              <div className="text-xs text-gray-500 font-mono mt-0.5">
                                {ev.instrument.ticker}{ev.instrument.isin ? ` · ${ev.instrument.isin}` : ''}
                              </div>
                            </Link>
                          </td>
                          <td className="py-2.5 pr-4">
                            <span className={ev.type === 'DIVIDEND' ? 'badge-green' : 'badge-gold'}>
                              {ev.type}
                            </span>
                          </td>
                          <td className="py-2.5 pr-4 tabular-nums text-emerald-400 font-medium">
                            {fmtEur(ev.amount)}
                          </td>
                          <td className="py-2.5 pr-4 text-gray-400">{ev.currency}</td>
                          <td className="py-2.5 pr-4 tabular-nums text-gray-300">
                            {fmtEur(ev.amount / (ev.fx_rate || 1))}
                          </td>
                          <td className="py-2.5">
                            <button
                              onClick={() => handleDelete(ev.id)}
                              disabled={deletingId === ev.id}
                              className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40"
                              title="Elimina"
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
