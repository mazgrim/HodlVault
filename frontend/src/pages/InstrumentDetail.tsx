import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceDot,
} from 'recharts'
import { ArrowLeft, TrendingUp, Wallet, BarChart2, Settings, AlertTriangle, RefreshCw, Plus, Loader2 } from 'lucide-react'
import KpiCard from '../components/KpiCard'
import ChangeBadge from '../components/ChangeBadge'
import { PageSpinner } from '../components/Spinner'
import InstrumentSettingsModal from '../components/InstrumentSettingsModal'
import CouponScheduleSection from '../components/CouponScheduleSection'
import { marketApi } from '../api'
import { fmtEur, fmtPct, fmtNum, fmtDate, fmtDateTime, fmtTime, pnlClass, pnlSign } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

// ── Periods ───────────────────────────────────────────────────────────────────

const PERIODS = ['1G', '1S', 'YTD', '1A', '3A', '5A', '10A', 'Max'] as const
type Period = typeof PERIODS[number]

// ── Types ─────────────────────────────────────────────────────────────────────

interface InstrumentInfo {
  id: number
  ticker: string
  isin: string | null
  name: string
  asset_class: string
  currency: string
  sector: string | null
  country: string | null
  price_source: string
  custom_url: string | null
  custom_jsonpath_price: string | null
  custom_jsonpath_date: string | null
  price_fetch_error: string | null
  price_fetch_error_at: string | null
  last_price_date: string | null
}

interface PositionKPI {
  quantity: number
  avg_cost: number
  current_price: number
  current_price_orig: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  weight_pct: number
  total_invested: number
}

interface TxRow {
  id: number
  date: string
  type: string
  quantity: number
  price: number
  fees: number
  currency: string
  fx_rate: number
  total_eur: number
}

interface DivRow {
  id: number
  date: string
  amount: number
  currency: string
  type: string
}

interface InstrumentDetailData {
  instrument: InstrumentInfo
  position: PositionKPI | null
  transactions: TxRow[]
  dividends: DivRow[]
  buy_dates: string[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const AC_BADGE: Record<string, string> = {
  ETF:        'badge-gold',
  EQUITY:     'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-900/40 text-blue-300 border border-blue-700/30',
  BOND:       'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-teal-900/40 text-teal-300 border border-teal-700/30',
  CRYPTO:     'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-900/40 text-purple-300 border border-purple-700/30',
  MUTUAL_FUND:'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-pink-900/40 text-pink-300 border border-pink-700/30',
}

function assetBadge(ac: string) {
  const cls = AC_BADGE[ac] ?? 'badge-gold'
  return <span className={cls}>{ac.replace('_', ' ')}</span>
}

const SOURCE_LABEL: Record<string, string> = {
  YAHOO: 'Yahoo Finance',
  MANUAL: 'Prezzo manuale',
  CUSTOM_JSON: 'Endpoint JSON',
}

const DIV_TYPE_LABEL: Record<string, string> = {
  DIVIDEND: 'DIVIDENDO',
  COUPON: 'CEDOLA',
  CERT_COUPON: 'CEDOLA CERT.',
}

/** Giorni interi trascorsi da una data ISO (0 = oggi). */
function daysSince(iso: string): number {
  const then = new Date(iso + 'T00:00:00').getTime()
  return Math.floor((Date.now() - then) / 86_400_000)
}

/** Find the nearest date in priceMap to `buyDate` (within ±5 calendar days). */
function nearestDate(buyDate: string, priceMap: Record<string, number>): string | null {
  if (priceMap[buyDate] != null) return buyDate
  for (let i = 1; i <= 5; i++) {
    for (const sign of [1, -1]) {
      const d = new Date(buyDate)
      d.setDate(d.getDate() + sign * i)
      const ds = d.toISOString().slice(0, 10)
      if (priceMap[ds] != null) return ds
    }
  }
  return null
}

/** SVG triangle pointing upward — used as buy marker on the chart. */
const TriangleUp = (props: any) => {
  const { cx, cy } = props
  if (cx == null || cy == null) return null
  const s = 6
  return (
    <polygon
      points={`${cx},${cy - s} ${cx - s * 0.85},${cy + s * 0.6} ${cx + s * 0.85},${cy + s * 0.6}`}
      fill="#10b981"
      stroke="#065f46"
      strokeWidth={1}
      opacity={0.9}
    />
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetail() {
  const { tooltip } = useChartTheme()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const instId = Number(id)

  const [detail, setDetail]         = useState<InstrumentDetailData | null>(null)
  const [chartPoints, setChartPoints] = useState<{ date: string; price: number }[]>([])
  const [period, setPeriod]         = useState<Period>('1A')
  const [loading, setLoading]       = useState(true)
  const [chartLoading, setChartLoading] = useState(false)

  // ── Fonte prezzo: impostazioni, inserimento manuale, refresh custom ────────
  const [showSettings, setShowSettings] = useState(false)
  const [showPriceForm, setShowPriceForm] = useState(false)
  const [manualDate, setManualDate]   = useState(new Date().toISOString().slice(0, 10))
  const [manualPrice, setManualPrice] = useState('')
  const [savingPrice, setSavingPrice] = useState(false)
  const [refreshingPrice, setRefreshingPrice] = useState(false)

  // ── Load detail ────────────────────────────────────────────────────────────
  const loadDetail = useCallback(async () => {
    if (!instId) return
    setLoading(true)
    try {
      const res = await marketApi.instrumentDetail(instId)
      setDetail(res.data)
    } catch {
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }, [instId])

  // ── Load price chart ───────────────────────────────────────────────────────
  const loadChart = useCallback(async () => {
    if (!instId) return
    setChartLoading(true)
    try {
      const res = await marketApi.instrumentPriceChart(instId, period)
      setChartPoints(res.data.points ?? [])
    } catch {
      setChartPoints([])
    } finally {
      setChartLoading(false)
    }
  }, [instId, period])

  useEffect(() => { loadDetail() }, [loadDetail])
  useEffect(() => { loadChart() }, [loadChart])

  // ── Fonte prezzo handlers ──────────────────────────────────────────────────
  const reloadAll = useCallback(async () => {
    await Promise.all([loadDetail(), loadChart()])
  }, [loadDetail, loadChart])

  const handleAddManualPrice = async () => {
    const p = parseFloat(manualPrice)
    if (!p || p <= 0) return
    setSavingPrice(true)
    try {
      await marketApi.addManualPrice(instId, { date: manualDate, price: p })
      setManualPrice('')
      setShowPriceForm(false)
      await reloadAll()
    } finally {
      setSavingPrice(false)
    }
  }

  const handleRefreshCustom = async () => {
    setRefreshingPrice(true)
    try {
      await marketApi.refreshInstrumentPrice(instId)
      await reloadAll()
    } finally {
      setRefreshingPrice(false)
    }
  }

  // ── Price lookup map ───────────────────────────────────────────────────────
  const priceMap = useMemo(() => {
    const m: Record<string, number> = {}
    chartPoints.forEach(p => { m[p.date] = p.price })
    return m
  }, [chartPoints])

  // ── Loading / error states ─────────────────────────────────────────────────
  if (loading) return <PageSpinner />
  if (!detail) {
    return (
      <div className="text-center py-20 text-gray-500">
        <p>Strumento non trovato.</p>
        <button onClick={() => navigate(-1)} className="mt-4 text-gold-500 hover:text-gold-400 text-sm transition-colors">
          ← Torna indietro
        </button>
      </div>
    )
  }

  const { instrument, position, transactions, dividends, buy_dates } = detail

  // ── Period change (from the visible chart): native price move first→last,
  // plus the EUR move on the held position (price delta at today's FX rate). ──
  let changePct: number | null = null
  let changeEur: number | null = null
  if (chartPoints.length >= 2) {
    const first = chartPoints[0].price
    const last = chartPoints[chartPoints.length - 1].price
    if (first) changePct = (last - first) / first * 100
    if (position && position.current_price) {
      const fx = position.current_price_orig / position.current_price  // orig units per EUR
      changeEur = position.quantity * (last - first) / (fx || 1)
    }
  }

  // ── Chart derived values ───────────────────────────────────────────────────
  const minPrice = chartPoints.length ? Math.min(...chartPoints.map(p => p.price)) * 0.97 : 0

  // Deduplicated, sorted buy dates
  const sortedBuyDates = [...new Set(buy_dates)].sort()
  const [firstBuyDate, ...otherBuyDates] = sortedBuyDates

  // Nearest chart date for the first buy (for the dashed reference line)
  const firstBuyChartDate = firstBuyDate ? nearestDate(firstBuyDate, priceMap) : null

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* Back */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
      >
        <ArrowLeft size={15} />
        Indietro
      </button>

      {/* ── Instrument Header ─────────────────────────────────────────────── */}
      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-start gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap mb-1">
              <h1 className="text-2xl font-bold text-gray-100 font-mono">{instrument.ticker}</h1>
              {assetBadge(instrument.asset_class)}
              <span className="text-xs text-gray-400 bg-navy-700/70 border border-gray-600/40 rounded px-2 py-0.5">
                {instrument.currency}
              </span>
              {instrument.price_source !== 'YAHOO' && (
                <span className="text-xs text-sky-300 bg-sky-900/40 border border-sky-700/30 rounded px-2 py-0.5">
                  {SOURCE_LABEL[instrument.price_source] ?? instrument.price_source}
                </span>
              )}
            </div>
            <p className="text-gray-300 text-sm">{instrument.name}</p>
            <div className="flex flex-wrap gap-4 mt-2 text-xs text-gray-500">
              {instrument.isin && (
                <span>ISIN: <span className="text-gray-400 font-mono">{instrument.isin}</span></span>
              )}
              {instrument.sector && (
                <span>Settore: <span className="text-gray-400">{instrument.sector}</span></span>
              )}
              {instrument.country && (
                <span>Paese: <span className="text-gray-400">{instrument.country}</span></span>
              )}
            </div>
          </div>
          <button
            onClick={() => setShowSettings(true)}
            title="Modifica nome, classe, valuta e fonte prezzo dello strumento"
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-600/40 rounded-lg px-2.5 py-1.5 transition-colors flex-shrink-0"
          >
            <Settings size={13} /> Impostazioni
          </button>
        </div>
      </div>

      {/* ── Fonte prezzo: stato / avvisi / azioni ─────────────────────────── */}
      {instrument.price_source === 'MANUAL' && (() => {
        const stale = instrument.last_price_date != null && daysSince(instrument.last_price_date) > 7
        return (
          <div className={`rounded-xl border px-4 py-3 text-sm ${
            stale ? 'bg-amber-900/20 border-amber-700/40' : 'bg-navy-800 border-gray-700/50'
          }`}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                {stale && <AlertTriangle size={15} className="text-amber-400 flex-shrink-0" />}
                <span className={stale ? 'text-amber-300' : 'text-gray-400'}>
                  {instrument.last_price_date
                    ? <>Ultimo aggiornamento manuale: <span className="font-medium">{fmtDate(instrument.last_price_date)}</span>
                        {stale && <> — più vecchio di 7 giorni ({daysSince(instrument.last_price_date)} gg)</>}</>
                    : 'Nessun prezzo inserito: aggiungi la prima quotazione.'}
                </span>
              </div>
              <button onClick={() => setShowPriceForm(v => !v)}
                className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5">
                <Plus size={13} /> Aggiorna prezzo
              </button>
            </div>
            {showPriceForm && (
              <div className="flex items-end gap-3 mt-3 flex-wrap">
                <div>
                  <label className="label">Data</label>
                  <input className="input" type="date" value={manualDate}
                    max={new Date().toISOString().slice(0, 10)}
                    onChange={e => setManualDate(e.target.value)} />
                </div>
                <div>
                  <label className="label">Prezzo ({instrument.currency})</label>
                  <input className="input tabular-nums" type="number" min="0" step="any" placeholder="0.00"
                    value={manualPrice} onChange={e => setManualPrice(e.target.value)} />
                </div>
                <button onClick={handleAddManualPrice}
                  disabled={savingPrice || !manualPrice}
                  className="btn-primary text-sm py-2 px-4">
                  {savingPrice ? <Loader2 size={14} className="animate-spin" /> : 'Salva'}
                </button>
                <p className="text-[11px] text-gray-500 w-full -mt-1">
                  Con una data passata aggiungi una quotazione storica; con la data di oggi aggiorni il prezzo corrente.
                </p>
              </div>
            )}
          </div>
        )
      })()}

      {instrument.price_source === 'CUSTOM_JSON' && (
        <div className={`rounded-xl border px-4 py-3 text-sm ${
          instrument.price_fetch_error ? 'bg-red-900/20 border-red-700/40' : 'bg-navy-800 border-gray-700/50'
        }`}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 min-w-0">
              {instrument.price_fetch_error ? (
                <>
                  <AlertTriangle size={15} className="text-red-400 flex-shrink-0" />
                  <span className="text-red-300">
                    Ultimo fetch fallito{instrument.price_fetch_error_at ? ` (${fmtDateTime(instrument.price_fetch_error_at)})` : ''}:{' '}
                    <span className="text-red-400/90">{instrument.price_fetch_error}</span>
                    {instrument.last_price_date && (
                      <span className="text-gray-400"> — mantenuto l'ultimo prezzo del {fmtDate(instrument.last_price_date)}</span>
                    )}
                  </span>
                </>
              ) : (
                <span className="text-gray-400">
                  Fonte JSON custom{instrument.last_price_date && <> — ultimo prezzo: <span className="font-medium text-gray-300">{fmtDate(instrument.last_price_date)}</span></>}
                </span>
              )}
            </div>
            <button onClick={handleRefreshCustom} disabled={refreshingPrice}
              className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5">
              <RefreshCw size={13} className={refreshingPrice ? 'animate-spin' : ''} /> Aggiorna ora
            </button>
          </div>
        </div>
      )}

      {/* ── Position KPIs ──────────────────────────────────────────────────── */}
      {position ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
          <KpiCard
            title="Quantità"
            value={fmtNum(position.quantity, 4)}
            icon={<BarChart2 size={16} />}
          />
          <KpiCard
            title="Prezzo Medio Carico"
            value={fmtEur(position.avg_cost)}
          />
          <KpiCard
            gold
            title="Valore Attuale"
            value={fmtEur(position.market_value)}
            icon={<Wallet size={16} />}
          />
          <KpiCard
            title="P&L Non Realizzato"
            value={`${pnlSign(position.unrealized_pnl)}${fmtEur(position.unrealized_pnl)}`}
            trend={position.unrealized_pnl_pct}
          />
          <KpiCard
            title="Peso Portafoglio"
            value={`${position.weight_pct.toFixed(1)}%`}
            icon={<TrendingUp size={16} />}
          />
        </div>
      ) : (
        <div className="card text-center py-6 text-gray-500 text-sm">
          Nessuna posizione aperta su questo strumento.
        </div>
      )}

      {/* ── Price Chart ────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div className="flex flex-col gap-1.5">
            <h2 className="text-base font-semibold text-gray-200">Prezzo Storico</h2>
            <ChangeBadge label={period} amount={changeEur} pct={changePct} />
          </div>
          <div className="flex gap-1 flex-wrap">
            {PERIODS.map(p => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  period === p
                    ? 'bg-gold-500/20 text-gold-500 border border-gold-500/30'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-navy-700'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {chartLoading ? (
          <div className="flex items-center justify-center h-64">
            <PageSpinner />
          </div>
        ) : chartPoints.length === 0 ? (
          <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
            Nessun dato storico disponibile per questo periodo.
          </div>
        ) : (
          <>
            {/* Legend */}
            {buy_dates.length > 0 && (
              <div className="flex gap-4 mb-3 text-xs text-gray-400">
                {firstBuyChartDate && (
                  <span className="flex items-center gap-1.5">
                    <svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#D4A017" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
                    Primo acquisto
                  </span>
                )}
                {otherBuyDates.length > 0 && (
                  <span className="flex items-center gap-1.5">
                    <svg width="12" height="12">
                      <polygon points="6,0 0,12 12,12" fill="#10b981" opacity="0.9" />
                    </svg>
                    Acquisti successivi
                  </span>
                )}
              </div>
            )}
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={chartPoints}>
                <defs>
                  <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#D4A017" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#D4A017" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => (period === '1G' && v?.includes('T')) ? fmtTime(v) : v?.slice(5)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[minPrice, 'auto']}
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) =>
                    v >= 1000
                      ? `${(v / 1000).toFixed(1)}k`
                      : v.toFixed(v >= 10 ? 0 : 2)
                  }
                  width={58}
                />
                <Tooltip
                  formatter={(v: number) => [
                    `${v.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 4 })} ${instrument.currency}`,
                    'Prezzo',
                  ]}
                  labelFormatter={(l) => (period === '1G' && String(l).includes('T')) ? fmtDateTime(l) : fmtDate(l)}
                  contentStyle={tooltip()}
                />
                <Area
                  type="monotone"
                  dataKey="price"
                  stroke="#D4A017"
                  strokeWidth={2}
                  fill="url(#priceGrad)"
                  dot={false}
                  activeDot={{ r: 4, fill: '#D4A017' }}
                />

                {/* First buy: dashed vertical reference line */}
                {firstBuyChartDate && (
                  <ReferenceLine
                    x={firstBuyChartDate}
                    stroke="#D4A017"
                    strokeDasharray="5 4"
                    strokeWidth={1.5}
                    label={{
                      value: '1° acq.',
                      position: 'insideTopRight',
                      fontSize: 9,
                      fill: '#D4A017',
                      dy: 4,
                    }}
                  />
                )}

                {/* Subsequent buy dates: upward triangle markers */}
                {otherBuyDates.map((bd) => {
                  const chartDate = nearestDate(bd, priceMap)
                  if (!chartDate) return null
                  const price = priceMap[chartDate]
                  if (price == null) return null
                  return (
                    <ReferenceDot
                      key={bd}
                      x={chartDate}
                      y={price}
                      r={0}
                      shape={<TriangleUp />}
                    />
                  )
                })}
              </AreaChart>
            </ResponsiveContainer>
          </>
        )}
      </div>

      {/* ── Piano Cedole (certificati) ────────────────────────────────────── */}
      <CouponScheduleSection
        instrumentId={instrument.id}
        currency={instrument.currency}
        quantity={position?.quantity ?? null}
        onChanged={loadDetail}
      />

      {/* ── Personal Transactions ─────────────────────────────────────────── */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">
          Transazioni Personali
          <span className="text-sm text-gray-500 font-normal ml-2">({transactions.length})</span>
        </h2>
        {transactions.length === 0 ? (
          <p className="text-gray-500 text-sm">Nessuna transazione registrata.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  {['Data', 'Tipo', 'Quantità', 'Prezzo', 'Comm.', 'Controvalore EUR'].map(h => (
                    <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase whitespace-nowrap last:pr-0">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.map(tx => (
                  <tr key={tx.id} className="table-row-hover border-b border-gray-700/20 last:border-0">
                    <td className="py-3 pr-4 text-gray-300 whitespace-nowrap">{fmtDate(tx.date)}</td>
                    <td className="py-3 pr-4">
                      <span className={
                        tx.type === 'BUY'
                          ? 'inline-block text-xs font-semibold text-emerald-400 bg-emerald-900/30 border border-emerald-700/30 rounded px-1.5 py-0.5'
                          : 'inline-block text-xs font-semibold text-red-400 bg-red-900/30 border border-red-700/30 rounded px-1.5 py-0.5'
                      }>
                        {tx.type === 'BUY' ? 'Acquisto' : 'Vendita'}
                      </span>
                    </td>
                    <td className="py-3 pr-4 tabular-nums text-gray-300">{fmtNum(tx.quantity, 4)}</td>
                    <td className="py-3 pr-4 tabular-nums text-gray-300">
                      {tx.price.toLocaleString('it-IT', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 4,
                      })} {tx.currency}
                    </td>
                    <td className="py-3 pr-4 tabular-nums text-gray-500">
                      {tx.fees > 0
                        ? `${tx.fees.toLocaleString('it-IT', { minimumFractionDigits: 2 })} ${tx.currency}`
                        : '—'}
                    </td>
                    <td className="py-3 tabular-nums text-gray-200 font-medium">{fmtEur(tx.total_eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Dividendi / Cedole ────────────────────────────────────────────── */}
      {dividends.length > 0 && (
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">
            Dividendi &amp; Cedole
            <span className="text-sm text-gray-500 font-normal ml-2">({dividends.length})</span>
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  {['Data', 'Tipo', 'Importo EUR'].map(h => (
                    <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase last:pr-0">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dividends.map(div => (
                  <tr key={div.id} className="table-row-hover border-b border-gray-700/20 last:border-0">
                    <td className="py-3 pr-4 text-gray-300 whitespace-nowrap">{fmtDate(div.date)}</td>
                    <td className="py-3 pr-4">
                      <span className={div.type === 'DIVIDEND' ? 'badge-green' : 'badge-gold'}>
                        {DIV_TYPE_LABEL[div.type] ?? div.type}
                      </span>
                    </td>
                    <td className="py-3 tabular-nums text-emerald-400 font-medium">{fmtEur(div.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Settings modal ────────────────────────────────────────────────── */}
      {showSettings && (
        <InstrumentSettingsModal
          instrument={instrument}
          onClose={() => setShowSettings(false)}
          onSaved={() => { setShowSettings(false); reloadAll() }}
        />
      )}
    </div>
  )
}
