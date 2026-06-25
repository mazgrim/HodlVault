import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceDot,
} from 'recharts'
import { ArrowLeft, TrendingUp, Wallet, BarChart2 } from 'lucide-react'
import KpiCard from '../components/KpiCard'
import { PageSpinner } from '../components/Spinner'
import { marketApi } from '../api'
import { fmtEur, fmtPct, fmtNum, fmtDate, pnlClass, pnlSign } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

// ── Periods ───────────────────────────────────────────────────────────────────

const PERIODS = ['YTD', '1A', '3A', '5A', '10A', 'Max'] as const
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
        </div>
      </div>

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
          <h2 className="text-base font-semibold text-gray-200">Prezzo Storico</h2>
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
                  tickFormatter={(v) => v?.slice(5)}
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
                  labelFormatter={(l) => fmtDate(l)}
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
                        {div.type}
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
    </div>
  )
}
