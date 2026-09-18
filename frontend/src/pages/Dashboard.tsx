import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Receipt, ChevronRight, ChevronDown, Archive } from 'lucide-react'
import KpiCard from '../components/KpiCard'
import ChangeBadge from '../components/ChangeBadge'
import InfoHint from '../components/InfoHint'
import TaxDetailModal from '../components/TaxDetailModal'
import PortfolioMultiSelect from '../components/PortfolioMultiSelect'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { marketApi } from '../api'
import { fmtEur, fmtPct, fmtNum, fmtDate, fmtAxisEur, pnlClass, pnlSign } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

const PERIODS = ['1G', '1S', '1M', '3M', '6M', 'YTD', '1Y', 'All'] as const

// Stima carico fiscale (Italia)
const BOLLO_RATE = 0.002     // 0,2% annuo — imposta di bollo su deposito titoli
const CG_RATE_STD = 0.26     // azioni / ETF / la maggior parte
const CG_RATE_BOND = 0.125   // titoli di Stato / obbligazioni white-list

function fmtAge(days: number): { value: string; subtitle: string } {
  if (days < 365) {
    const months = Math.round(days / 30.5)
    return {
      value:    `${days}g`,
      subtitle: months > 0 ? `${months} mes${months === 1 ? 'e' : 'i'}` : '',
    }
  }
  const years  = Math.floor(days / 365)
  const months = Math.round((days - years * 365) / 30.5)
  const monthsNorm = months === 12 ? 0 : months          // edge-case: 11.5 → rounds to 12
  const yearsNorm  = months === 12 ? years + 1 : years
  return {
    value:    monthsNorm > 0 ? `${yearsNorm}a ${monthsNorm}m` : `${yearsNorm}a`,
    subtitle: `${days} giorni`,
  }
}

interface KPIs {
  total_value: number
  total_invested: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  realized_pnl: number
  realized_trade_pnl: number
  realized_dividends: number
  total_pnl: number
  annualized_return: number | null
  portfolio_age_days: number
  as_of_date: string
}

interface Position {
  instrument_id: number
  ticker: string
  name: string
  isin: string | null
  asset_class: string
  currency: string
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

interface ClosedPosition {
  instrument_id: number
  ticker: string
  name: string
  isin: string | null
  currency: string
  quantity: number
  avg_buy_price: number
  avg_sell_price: number
  buy_value: number
  sell_value: number
  realized_pnl: number
  realized_pnl_pct: number
  realized_pnl_net: number
  current_price: number | null
  current_value: number | null
  first_buy_date: string | null
  last_sell_date: string | null
}

export default function Dashboard() {
  const { tooltip } = useChartTheme()
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPfs, setSelectedPfs] = useState<number[]>([])   // vuoto = tutti
  const [kpis, setKpis] = useState<KPIs | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [chart, setChart] = useState<{ date: string; value: number }[]>([])
  const [chartChange, setChartChange] = useState<{ abs: number | null; pct: number | null }>({ abs: null, pct: null })
  const [period, setPeriod] = useState<string>('1Y')
  const [loading, setLoading] = useState(true)
  const [pnlMode, setPnlMode] = useState<'unrealized' | 'realized'>('unrealized')
  const [showTaxDetail, setShowTaxDetail] = useState(false)
  const [closed, setClosed] = useState<ClosedPosition[]>([])
  const [closedCollapsed, setClosedCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem('dash_closed_collapsed') === '1' } catch { return false }
  })
  const toggleClosed = () => setClosedCollapsed(v => {
    const next = !v
    try { localStorage.setItem('dash_closed_collapsed', next ? '1' : '0') } catch { /* ignore */ }
    return next
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [kRes, pRes, cRes, clRes] = await Promise.all([
        marketApi.kpis(selectedPfs),
        marketApi.positions(selectedPfs),
        marketApi.chart(selectedPfs, period),
        marketApi.closedPositions(selectedPfs),
      ])
      setKpis(kRes.data)
      setPositions(pRes.data)
      setClosed(clRes.data)
      setChart(cRes.data.points)
      setChartChange({ abs: cRes.data.change ?? null, pct: cRes.data.change_pct ?? null })
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [selectedPfs, period])

  useEffect(() => { load() }, [load])

  if (pfLoading) return <PageSpinner />

  const chartData = chart.map((p) => ({ date: p.date, valore: p.value }))
  const minVal = chart.length ? Math.min(...chart.map((p) => p.value)) * 0.98 : 0

  // ── Stima tasse sul portafoglio attuale ─────────────────────────────────────
  const taxValue = positions.reduce((s, p) => s + p.market_value, 0)
  const bollo = taxValue * BOLLO_RATE
  // Base imponibile = solo le posizioni in plusvalenza (minus non compensate)
  const taxableGain = positions.reduce((s, p) => p.unrealized_pnl > 0 ? s + p.unrealized_pnl : s, 0)
  const taxRows = positions.map((p) => {
    const rate = p.asset_class === 'BOND' ? CG_RATE_BOND : CG_RATE_STD
    return {
      instrument_id: p.instrument_id,
      name: p.name,
      ticker: p.ticker,
      market_value: p.market_value,
      gain: p.unrealized_pnl,
      rate,
      tax: p.unrealized_pnl > 0 ? p.unrealized_pnl * rate : 0,
    }
  })
  const capitalGainTax = taxRows.reduce((s, r) => s + r.tax, 0)
  const netLiquidation = taxValue - capitalGainTax

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100">Dashboard</h1>
        <PortfolioMultiSelect portfolios={portfolios} selected={selectedPfs} onChange={setSelectedPfs} />
      </div>

      {loading ? (
        <PageSpinner />
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <KpiCard
              gold
              center
              title="Valore Totale"
              value={fmtEur(kpis?.total_value ?? 0)}
              subtitle={kpis?.as_of_date ? `Al ${fmtDate(kpis.as_of_date)}` : ''}
            />

            {/* P&L card — toggle Non Realizzato / Realizzato */}
            <div className="card border-gray-700/40 flex flex-col items-center text-center gap-2">
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">P&amp;L</span>

              {/* Toggle */}
              <div className="inline-flex items-center gap-1 text-[11px] font-medium">
                {([['unrealized', 'Non Realizzato'], ['realized', 'Realizzato']] as const).map(([mode, label]) => (
                  <button
                    key={mode}
                    onClick={() => setPnlMode(mode)}
                    className={`px-2.5 py-0.5 rounded-full transition-colors ${
                      pnlMode === mode
                        ? 'bg-emerald-500 text-navy-900'
                        : 'text-gray-400 hover:text-gray-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* Value + detail */}
              <div className="flex-1 flex flex-col justify-center">
                {pnlMode === 'unrealized' ? (
                  <>
                    <div className="flex items-baseline justify-center gap-2 flex-wrap">
                      <span className={`text-xl sm:text-2xl font-bold tabular-nums ${pnlClass(kpis?.unrealized_pnl ?? 0)}`}>
                        {pnlSign(kpis?.unrealized_pnl ?? 0)}{fmtEur(kpis?.unrealized_pnl ?? 0)}
                      </span>
                      {kpis?.unrealized_pnl_pct !== undefined && (
                        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                          kpis.unrealized_pnl_pct >= 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                        }`}>
                          {pnlSign(kpis.unrealized_pnl_pct)}{fmtPct(kpis.unrealized_pnl_pct)}
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-gray-600 mt-1">Plusvalenze su posizioni aperte</div>
                  </>
                ) : (
                  <>
                    <span className={`text-xl sm:text-2xl font-bold tabular-nums ${pnlClass(kpis?.realized_pnl ?? 0)}`}>
                      {pnlSign(kpis?.realized_pnl ?? 0)}{fmtEur(kpis?.realized_pnl ?? 0)}
                    </span>
                    <div className="text-[11px] text-gray-500 mt-1.5 space-y-0.5">
                      <div>Trade: {pnlSign(kpis?.realized_trade_pnl ?? 0)}{fmtEur(kpis?.realized_trade_pnl ?? 0)}</div>
                      <div>Dividendi / Cedole: {pnlSign(kpis?.realized_dividends ?? 0)}{fmtEur(kpis?.realized_dividends ?? 0)}</div>
                    </div>
                  </>
                )}
              </div>
            </div>

            <KpiCard
              center
              title="Capitale Investito"
              value={fmtEur(kpis?.total_invested ?? 0)}
            />
            <KpiCard
              center
              title="P&L Totale"
              value={`${pnlSign(kpis?.total_pnl ?? 0)}${fmtEur(kpis?.total_pnl ?? 0)}`}
              colorByValue={kpis?.total_pnl}
              subtitle="Non Realizzato + Realizzato"
            />
            <KpiCard
              center
              title="Rendimento Annualizzato"
              value={kpis?.annualized_return != null ? fmtPct(kpis.annualized_return, true) : 'N/D'}
              subtitle={kpis?.annualized_return == null ? 'Storico insufficiente' : undefined}
            />
            <KpiCard
              center
              title="Età Portafoglio"
              value={fmtAge(kpis?.portfolio_age_days ?? 0).value}
              subtitle={fmtAge(kpis?.portfolio_age_days ?? 0).subtitle}
            />
          </div>

          {/* Chart */}
          <div className="card">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              {/* Variazione in linea col titolo: più leggibile e non allunga la card.
                  Su schermi stretti va a capo da sola. */}
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="text-base font-semibold text-gray-200">Valore nel Tempo</h2>
                <ChangeBadge label={period} amount={chartChange.abs} pct={chartChange.pct} size="lg" />
              </div>
              <div className="flex gap-1 flex-wrap">
                {PERIODS.map((p) => (
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
            {chartData.length === 0 ? (
              <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
                Nessun dato disponibile. Importa delle transazioni per iniziare.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="valGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#D4A017" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#D4A017" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v?.slice(5)} />
                  <YAxis
                    domain={[minVal, 'auto']}
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => fmtAxisEur(v)}
                    width={64}
                  />
                  <Tooltip
                    formatter={(v: number) => [fmtEur(v), 'Valore']}
                    labelFormatter={(l) => fmtDate(l)}
                    contentStyle={tooltip()}
                  />
                  <Area
                    type="monotone"
                    dataKey="valore"
                    stroke="#D4A017"
                    strokeWidth={2}
                    fill="url(#valGrad)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Tax estimate */}
          {positions.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between gap-3 mb-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold text-gray-200">Tasse (stima)</h2>
                  <InfoHint text="Stima del carico fiscale sul portafoglio attuale. Capital gain: 26% su azioni/ETF, 12,5% su titoli di Stato/obbligazioni white-list, applicato solo alle posizioni in plusvalenza (le minusvalenze non sono compensate). I bond corporate rientrerebbero al 26%. Bollo titoli: 0,2% annuo sul valore. Valori indicativi, non costituiscono consulenza fiscale." />
                </div>
                <button
                  onClick={() => setShowTaxDetail(true)}
                  className="flex items-center gap-1.5 flex-shrink-0 text-xs font-semibold px-3 py-1.5 rounded-lg border border-gold-500/50 bg-gold-500/15 text-gold-300 hover:bg-gold-500/25 transition-colors"
                >
                  <Receipt size={14} />
                  Dettaglio per titolo
                  <ChevronRight size={14} />
                </button>
              </div>
              <p className="text-xs text-gray-500 mb-4">Quanto costa tenere il portafoglio e quanto resterebbe vendendo tutto oggi.</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <KpiCard
                  title="Imposta di bollo (annua)"
                  value={fmtEur(bollo)}
                  subtitle="0,2% del valore"
                />
                <KpiCard
                  title="Imposta sul capital gain"
                  value={fmtEur(capitalGainTax)}
                  subtitle={`26%/12,5% su ${fmtEur(taxableGain)} di plusvalenze`}
                />
                <KpiCard
                  gold
                  title="Netto di liquidazione"
                  value={fmtEur(netLiquidation)}
                  subtitle={`valore attuale ${fmtEur(taxValue)} − capital gain`}
                />
              </div>
            </div>
          )}

          {/* Positions Table */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Posizioni Aperte</h2>
            {positions.length === 0 ? (
              <p className="text-gray-500 text-sm">Nessuna posizione aperta.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700/50">
                      {['Strumento', 'Qtà', 'Prezzo Medio', 'Prezzo Attuale', 'P&L €', 'P&L %', 'Valore', 'Peso %'].map((h) => (
                        <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.instrument_id} className="table-row-hover border-b border-gray-700/20">
                        <td className="py-3 pr-4">
                          <Link to={`/instruments/${pos.instrument_id}`} className="group">
                            <div className="font-semibold text-gray-100 group-hover:text-gold-400 transition-colors break-words leading-snug max-w-[240px]" title={pos.name}>{pos.name}</div>
                            <div className="text-xs text-gray-500 font-mono mt-0.5">
                              {pos.ticker}{pos.isin ? ` · ${pos.isin}` : ''}
                            </div>
                          </Link>
                        </td>
                        <td className="py-3 pr-4 tabular-nums text-gray-300">{fmtNum(pos.quantity, 4)}</td>
                        <td className="py-3 pr-4 tabular-nums text-gray-300">{fmtEur(pos.avg_cost)}</td>
                        <td className="py-3 pr-4">
                          <div className="tabular-nums text-gray-300">{fmtEur(pos.current_price)}</div>
                          <div className="text-xs text-gray-500">{pos.currency}</div>
                        </td>
                        <td className={`py-3 pr-4 tabular-nums font-medium ${pnlClass(pos.unrealized_pnl)}`}>
                          {pnlSign(pos.unrealized_pnl)}{fmtEur(pos.unrealized_pnl)}
                        </td>
                        <td className={`py-3 pr-4 tabular-nums font-medium ${pnlClass(pos.unrealized_pnl_pct)}`}>
                          {pnlSign(pos.unrealized_pnl_pct)}{fmtPct(pos.unrealized_pnl_pct)}
                        </td>
                        <td className="py-3 pr-4 tabular-nums text-gray-200 font-medium">{fmtEur(pos.market_value)}</td>
                        <td className="py-3 tabular-nums text-gray-400">
                          <div className="flex items-center gap-2">
                            <div className="w-12 bg-navy-700 rounded-full h-1.5">
                              <div className="bg-gold-500 h-1.5 rounded-full" style={{ width: `${Math.min(pos.weight_pct, 100)}%` }} />
                            </div>
                            <span>{pos.weight_pct.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Closed Positions (collapsible) */}
          {closed.length > 0 && (
            <div className="card">
              <button
                onClick={toggleClosed}
                className="w-full flex items-center justify-between gap-3 text-left"
                aria-expanded={!closedCollapsed}
              >
                <div className="flex items-center gap-2">
                  <Archive size={16} className="text-gray-400" />
                  <h2 className="text-base font-semibold text-gray-200">Posizioni Chiuse</h2>
                  <span className="text-xs text-gray-500">({closed.length})</span>
                </div>
                <div className="flex items-center gap-3">
                  {(() => {
                    const tot = closed.reduce((s, c) => s + c.realized_pnl, 0)
                    return (
                      <span className={`text-sm font-semibold tabular-nums ${pnlClass(tot)}`}>
                        {pnlSign(tot)}{fmtEur(tot)}
                      </span>
                    )
                  })()}
                  <ChevronDown size={18} className={`text-gray-400 transition-transform ${closedCollapsed ? '' : 'rotate-180'}`} />
                </div>
              </button>

              {!closedCollapsed && (
                <div className="overflow-x-auto mt-4">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-700/50">
                        {['Strumento', 'Qtà', 'Acquisto', 'Vendita', 'P&L lordo', 'P&L netto', 'Valore Attuale'].map((h) => (
                          <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {closed.map((c) => (
                        <tr key={c.instrument_id} className="table-row-hover border-b border-gray-700/20">
                          <td className="py-3 pr-4">
                            <Link to={`/instruments/${c.instrument_id}`} className="group">
                              <div className="font-semibold text-gray-100 group-hover:text-gold-400 transition-colors break-words leading-snug max-w-[240px]" title={c.name}>{c.name}</div>
                              <div className="text-xs text-gray-500 font-mono mt-0.5">
                                {c.ticker}{c.last_sell_date ? ` · chiusa il ${fmtDate(c.last_sell_date)}` : ''}
                              </div>
                            </Link>
                          </td>
                          <td className="py-3 pr-4 tabular-nums text-gray-300">{fmtNum(c.quantity, 4)}</td>
                          <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                            <div className="text-gray-300">{fmtEur(c.avg_buy_price)}</div>
                            <div className="text-xs text-gray-500">{fmtEur(c.buy_value)}</div>
                          </td>
                          <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                            <div className="text-gray-300">{fmtEur(c.avg_sell_price)}</div>
                            <div className="text-xs text-gray-500">{fmtEur(c.sell_value)}</div>
                          </td>
                          <td className={`py-3 pr-4 tabular-nums font-medium whitespace-nowrap ${pnlClass(c.realized_pnl)}`}>
                            <div>{pnlSign(c.realized_pnl)}{fmtEur(c.realized_pnl)}</div>
                            <div className="text-xs font-normal opacity-80">{pnlSign(c.realized_pnl_pct)}{fmtPct(c.realized_pnl_pct)}</div>
                          </td>
                          <td className={`py-3 pr-4 tabular-nums font-medium ${pnlClass(c.realized_pnl_net)}`}>
                            {pnlSign(c.realized_pnl_net)}{fmtEur(c.realized_pnl_net)}
                          </td>
                          <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                            {c.current_price != null ? (
                              <>
                                <div className="text-gray-300">{fmtEur(c.current_price)}</div>
                                <div className="text-xs text-gray-500">{c.current_value != null ? fmtEur(c.current_value) : ''}</div>
                              </>
                            ) : <span className="text-gray-400">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[11px] text-gray-600 mt-3">
                    Sotto ogni prezzo (medio o attuale) è indicato il controvalore totale (prezzo × quantità). "P&L netto" sottrae
                    la stima dell'imposta sul capital gain (26% azioni/ETF, 12,5% bond white-list; nessuna imposta sulle
                    minusvalenze, senza compensazione dello zainetto). "Valore Attuale" = prezzo di oggi × quantità venduta.
                  </p>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {showTaxDetail && (
        <TaxDetailModal rows={taxRows} onClose={() => setShowTaxDetail(false)} />
      )}
    </div>
  )
}
