import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import PortfolioSelector from '../components/PortfolioSelector'
import InfoHint from '../components/InfoHint'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { marketApi } from '../api'
import { fmtEur, fmtPct, fmtNum } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

// Palette base ad alto contrasto: colori ben separati così le fette vicine NON si
// confondono. Ogni grafico parte da un punto diverso (rotazione), così i colori
// dominanti cambiano da torta a torta pur mantenendo il contrasto interno.
const MASTER = [
  '#D4A017', '#3B82F6', '#EF4444', '#10B981', '#A855F7', '#F97316',
  '#06B6D4', '#EC4899', '#84CC16', '#6366F1', '#F43F5E', '#EAB308',
]
const rot = (a: string[], n: number) => a.slice(n).concat(a.slice(0, n))
const PALETTE_CATEGORIA = rot(MASTER, 0)   // parte dall'oro
const PALETTE_SETTORE   = rot(MASTER, 3)   // parte dal verde
const PALETTE_PAESE     = rot(MASTER, 6)   // parte dal ciano
const PALETTE_VALUTA    = rot(MASTER, 9)   // parte dall'indaco

interface AllocationItem { label: string; value: number; weight_pct: number; via_etf_pct?: number }
interface PositionRow {
  instrument_id: number; ticker: string; name: string; isin: string | null
  market_value: number; weight_pct: number
  unrealized_pnl: number; unrealized_pnl_pct: number; currency: string
}
interface CompanyExposure {
  name: string; symbol: string | null; value: number; weight_pct: number
  direct_value: number; via_etf_value: number
  direct_pct: number; via_etf_pct: number
}
interface AnalysisData {
  by_asset_class: AllocationItem[]
  by_sector: AllocationItem[]
  by_country: AllocationItem[]
  by_currency: AllocationItem[]
  top_holdings: PositionRow[]
  concentration: {
    top5_weight: number; hhi: number
    top5_weight_lookthrough: number; hhi_lookthrough: number
    top_name: string | null; top_name_pct: number
  }
  company_exposure: CompanyExposure[]
  lookthrough_coverage_pct: number
}

function DonutChart({ data, title, colors }: { data: AllocationItem[]; title: string; colors: string[] }) {
  const { tooltip, tooltipText } = useChartTheme()
  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">{title}</h3>
      {data.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-gray-500 text-sm">Nessun dato</div>
      ) : (
        <div className="flex flex-col items-center">
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" innerRadius={55} outerRadius={85} dataKey="value" paddingAngle={2}>
                {data.map((_, i) => (
                  <Cell key={i} fill={colors[i % colors.length]} stroke="transparent" />
                ))}
              </Pie>
              <Tooltip
                formatter={(v: number, _n, { payload }) => [
                  `${fmtEur(v)} (${payload.weight_pct.toFixed(1)}%)`,
                  payload.label,
                ]}
                contentStyle={tooltip()}
                itemStyle={tooltipText}
                labelStyle={tooltipText}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="w-full space-y-1 mt-2">
            {data.slice(0, 6).map((item, i) => (
              <div key={item.label} className="flex items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: colors[i % colors.length] }} />
                  <span className="text-gray-300 truncate">{item.label}</span>
                </div>
                <span className="text-gray-400 tabular-nums whitespace-nowrap flex-shrink-0">
                  {item.weight_pct.toFixed(1)}%
                  {item.via_etf_pct && !item.label.includes('(ETF)')
                    ? <span className="text-gray-600"> ({item.via_etf_pct.toFixed(1)}% ETF)</span> : null}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ConcBar({ label, valueText, pct, max, color }: { label: string; valueText: string; pct: number; max: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-gray-500">{label}</span>
        <span className="text-gray-200 font-medium tabular-nums">{valueText}</span>
      </div>
      <div className="w-full bg-navy-700 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${Math.min((pct / max) * 100, 100)}%` }} />
      </div>
    </div>
  )
}

export default function Analysis() {
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPf, setSelectedPf] = useState<number | null>(null)
  const [data, setData] = useState<AnalysisData | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await marketApi.analysis(selectedPf ?? undefined)
      setData(res.data)
    } finally {
      setLoading(false)
    }
  }, [selectedPf])

  useEffect(() => { load() }, [load])

  if (pfLoading) return <PageSpinner />

  // HHI interpretation
  function hhiLabel(hhi: number): { label: string; color: string } {
    if (hhi < 1500) return { label: 'Diversificato', color: 'text-emerald-400' }
    if (hhi < 2500) return { label: 'Moderatamente concentrato', color: 'text-amber-400' }
    return { label: 'Concentrato', color: 'text-red-400' }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100">Analisi Portafoglio</h1>
        <PortfolioSelector portfolios={portfolios} selected={selectedPf} onChange={setSelectedPf} />
      </div>

      {loading ? <PageSpinner /> : !data ? (
        <div className="text-gray-500 text-sm">Nessun dato disponibile.</div>
      ) : (
        <>
          {/* Allocation charts */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <DonutChart data={data.by_asset_class} title="Per Categoria" colors={PALETTE_CATEGORIA} />
            <DonutChart data={data.by_sector} title="Per Settore" colors={PALETTE_SETTORE} />
            <DonutChart data={data.by_country} title="Per Area Geografica" colors={PALETTE_PAESE} />
            <DonutChart data={data.by_currency} title="Per Valuta" colors={PALETTE_VALUTA} />
          </div>

          {/* Concentration risk */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">Rischio di Concentrazione</h3>

              {data.concentration.top_name && (
                <div className="flex justify-between items-center text-xs mb-4 pb-3 border-b border-gray-700/40">
                  <span className="flex items-center gap-1.5 text-gray-500">
                    Maggiore esposizione singola
                    <InfoHint text="Il singolo nome (azienda, Bitcoin, oro…) a cui sei più esposto, calcolato 'look-through': cioè guardando dentro gli ETF e sommando la quota detenuta direttamente a quella contenuta nei fondi. La vista 'per strumento' invece tratta ogni ETF come una sola posizione, senza guardarci dentro." />
                  </span>
                  <span className="text-gray-200 font-semibold">{data.concentration.top_name} · {fmtPct(data.concentration.top_name_pct)}</span>
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <div className="flex items-center gap-1.5 text-xs font-medium text-gray-400 mb-1.5">
                    Prime 5 Posizioni
                    <InfoHint text="Quota del portafoglio investita nelle 5 posizioni più grandi. Più è alta, più il portafoglio dipende da pochi elementi: oltre ~60% è generalmente considerato concentrato. 'Per strumento' conta ogni posizione com'è; 'look-through' aggrega per singolo nome guardando dentro gli ETF." />
                  </div>
                  <div className="space-y-2">
                    <ConcBar label="Per strumento" valueText={fmtPct(data.concentration.top5_weight)}
                      pct={data.concentration.top5_weight} max={100}
                      color={data.concentration.top5_weight > 60 ? 'bg-red-500' : 'bg-emerald-500'} />
                    <ConcBar label="Per azienda (look-through)" valueText={fmtPct(data.concentration.top5_weight_lookthrough)}
                      pct={data.concentration.top5_weight_lookthrough} max={100}
                      color={data.concentration.top5_weight_lookthrough > 60 ? 'bg-red-500' : 'bg-emerald-500'} />
                  </div>
                </div>

                <div>
                  <div className="flex items-center gap-1.5 text-xs font-medium text-gray-400 mb-1.5">
                    Indice HHI
                    <InfoHint text="Indice di Herfindahl-Hirschman: misura quanto è concentrato il portafoglio sommando i quadrati dei pesi di ogni elemento, su scala 0–10.000. Più è alto, più sei esposto a pochi nomi (una sola posizione = 10.000; 10 posizioni uguali = 1.000). Soglie: sotto 1.500 diversificato, 1.500–2.500 moderatamente concentrato, oltre 2.500 concentrato." />
                  </div>
                  <div className="space-y-2">
                    <ConcBar label={`Per strumento — ${hhiLabel(data.concentration.hhi).label}`}
                      valueText={fmtNum(data.concentration.hhi, 0)} pct={data.concentration.hhi} max={10000} color="bg-gold-500" />
                    <ConcBar label={`Look-through — ${hhiLabel(data.concentration.hhi_lookthrough).label}`}
                      valueText={fmtNum(data.concentration.hhi_lookthrough, 0)} pct={data.concentration.hhi_lookthrough} max={10000} color="bg-gold-500" />
                  </div>
                  <div className="flex justify-between text-xs text-gray-600 mt-1.5">
                    <span>0 — Diversificato</span>
                    <span>10.000 — 1 nome</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Posizioni principali */}
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">Posizioni Principali</h3>
              <div className="space-y-2">
                {data.top_holdings.slice(0, 8).map((pos, i) => (
                  <div key={pos.ticker} className="flex items-center gap-3">
                    <span className="text-xs text-gray-500 w-4 text-right flex-shrink-0">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between items-start mb-0.5">
                        <Link to={`/instruments/${pos.instrument_id}`} className="group flex-1 min-w-0 mr-2">
                          <div className="text-sm font-medium text-gray-200 group-hover:text-gold-400 transition-colors truncate leading-tight">{pos.name}</div>
                          <div className="text-xs text-gray-500 font-mono">{pos.ticker}</div>
                        </Link>
                        <span className="text-sm text-gray-300 tabular-nums flex-shrink-0">{fmtEur(pos.market_value)}</span>
                      </div>
                      <div className="w-full bg-navy-700 rounded-full h-1">
                        <div
                          className="h-1 rounded-full bg-gold-500/70"
                          style={{ width: `${Math.min(pos.weight_pct, 100)}%` }}
                        />
                      </div>
                    </div>
                    <span className="text-xs text-gray-400 w-10 text-right flex-shrink-0">{pos.weight_pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Esposizione per azienda (look-through ETF) */}
          {data.company_exposure.length > 0 && (
            <div className="card">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 mb-1">
                <h2 className="text-base font-semibold text-gray-200">Esposizione per Azienda (look-through)</h2>
                <span className="text-xs text-gray-500">
                  Considera le aziende detenute anche dentro gli ETF · copertura ETF {data.lookthrough_coverage_pct.toFixed(0)}% (prime 10 posizioni di ogni ETF)
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700/50">
                      {['#', 'Azienda', 'Diretta', 'Via ETF', 'Totale', 'Peso %'].map((h) => (
                        <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.company_exposure.map((c, i) => (
                      <tr key={(c.symbol || c.name) + i} className="table-row-hover border-b border-gray-700/20">
                        <td className="py-2.5 pr-4 text-gray-500 text-xs">{i + 1}</td>
                        <td className="py-2.5 pr-4">
                          <div className="font-medium text-gray-100 truncate max-w-[220px]">{c.name}</div>
                          {c.symbol && <div className="text-xs text-gray-500 font-mono mt-0.5">{c.symbol}</div>}
                        </td>
                        <td className="py-2.5 pr-4 tabular-nums text-gray-400">{c.direct_value > 0 ? fmtEur(c.direct_value) : '—'}</td>
                        <td className="py-2.5 pr-4 tabular-nums text-gray-400">{c.via_etf_value > 0 ? fmtEur(c.via_etf_value) : '—'}</td>
                        <td className="py-2.5 pr-4 tabular-nums text-gray-200 font-medium">{fmtEur(c.value)}</td>
                        <td className="py-2.5 tabular-nums">
                          <span className="text-gold-400 font-semibold">{c.weight_pct.toFixed(2)}%</span>
                          {c.via_etf_pct > 0 && (
                            <span className="text-gray-500 text-xs ml-1">({c.via_etf_pct.toFixed(2)}% in ETF)</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tabella completa delle posizioni */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Tabella Posizioni</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700/50">
                    {['#', 'Strumento', 'Valuta', 'Valore', 'Peso %', 'P&L', 'P&L %'].map((h) => (
                      <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.top_holdings.map((pos, i) => (
                    <tr key={pos.ticker} className="table-row-hover border-b border-gray-700/20">
                      <td className="py-2.5 pr-4 text-gray-500 text-xs">{i + 1}</td>
                      <td className="py-2.5 pr-4">
                        <Link to={`/instruments/${pos.instrument_id}`} className="group">
                          <div className="font-semibold text-gray-100 group-hover:text-gold-400 transition-colors truncate max-w-[220px]">{pos.name}</div>
                          <div className="text-xs text-gray-500 font-mono mt-0.5">
                            {pos.ticker}{pos.isin ? ` · ${pos.isin}` : ''}
                          </div>
                        </Link>
                      </td>
                      <td className="py-2.5 pr-4">
                        <span className="badge-gold">{pos.currency}</span>
                      </td>
                      <td className="py-2.5 pr-4 tabular-nums text-gray-200">{fmtEur(pos.market_value)}</td>
                      <td className="py-2.5 pr-4 tabular-nums text-gray-400">{pos.weight_pct.toFixed(1)}%</td>
                      <td className={`py-2.5 pr-4 tabular-nums font-medium ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.unrealized_pnl >= 0 ? '+' : ''}{fmtEur(pos.unrealized_pnl)}
                      </td>
                      <td className={`py-2.5 tabular-nums font-medium ${pos.unrealized_pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.unrealized_pnl_pct >= 0 ? '+' : ''}{fmtPct(pos.unrealized_pnl_pct)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
