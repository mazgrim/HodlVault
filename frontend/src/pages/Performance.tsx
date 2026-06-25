import { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import PortfolioSelector from '../components/PortfolioSelector'
import InfoHint from '../components/InfoHint'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { perfApi } from '../api'
import { fmtPct, fmtNum, pnlClass, pnlSign, MONTH_NAMES } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

interface PeriodicReturn { period: string; portfolio_return: number | null; benchmark_return: number | null }
interface MonthlyReturn { year: number; month: number; return_pct: number }
interface DrawdownPoint { date: string; drawdown: number }
interface Metrics {
  sharpe_ratio: number | null
  volatility_annual: number | null
  max_drawdown: number | null
  period_returns: PeriodicReturn[]
}

export default function Performance() {
  const { tooltip, dark } = useChartTheme()
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPf, setSelectedPf] = useState<number | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [monthly, setMonthly] = useState<MonthlyReturn[]>([])
  const [drawdown, setDrawdown] = useState<DrawdownPoint[]>([])
  const [cumulative, setCumulative] = useState<{ date: string; value: number }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setMetrics(null)
    setMonthly([])
    setDrawdown([])
    setCumulative([])

    // Start all 4 requests in parallel immediately
    const metricsPromise = perfApi.metrics(selectedPf ?? undefined)

    try {
      const [monthRes, ddRes, cumRes] = await Promise.all([
        perfApi.monthlyReturns(selectedPf ?? undefined),
        perfApi.drawdown(selectedPf ?? undefined),
        perfApi.cumulative(selectedPf ?? undefined),
      ])
      setMonthly(monthRes.data ?? [])
      setDrawdown(ddRes.data ?? [])
      setCumulative(cumRes.data?.points ?? [])
    } catch (err: any) {
      console.error('Performance charts failed:', err)
      setError('Impossibile caricare i dati di performance.')
    } finally {
      setLoading(false)
    }

    try {
      const mRes = await metricsPromise
      setMetrics(mRes.data)
    } catch (err: any) {
      console.error('Metrics load failed:', err?.response?.data ?? err)
    }
  }, [selectedPf])

  useEffect(() => { load() }, [load])

  if (pfLoading) return <PageSpinner />

  // Build heatmap data: group by year
  const heatYears = [...new Set(monthly.map((r) => r.year))].sort()
  const heatMap: Record<number, Record<number, number | null>> = {}
  for (const year of heatYears) {
    heatMap[year] = {}
    for (let m = 1; m <= 12; m++) {
      const entry = monthly.find((r) => r.year === year && r.month === m)
      heatMap[year][m] = entry ? entry.return_pct : null
    }
  }

  const cumulativeData = cumulative.map((p, i) => {
    const base = cumulative[0]?.value || 1
    return { date: p.date, return_pct: ((p.value - base) / base) * 100 }
  })

  const periodReturns = metrics?.period_returns ?? []
  const maxAbsReturn = Math.max(
    ...periodReturns.filter(r => r.portfolio_return != null).map(r => Math.abs(r.portfolio_return!)),
    0.01
  )

  function heatColor(val: number | null): string {
    if (val === null) return dark ? '#1a1a2e' : '#e2e8f0'
    if (val > 5) return '#065f46'
    if (val > 2) return '#047857'
    if (val > 0.5) return '#059669'
    if (val > 0) return '#10b981'
    if (val > -0.5) return '#fca5a5'
    if (val > -2) return '#f87171'
    if (val > -5) return '#ef4444'
    return '#b91c1c'
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100">Performance</h1>
        <PortfolioSelector portfolios={portfolios} selected={selectedPf} onChange={setSelectedPf} />
      </div>

      {loading ? <PageSpinner /> : error ? (
        <div className="card border border-red-500/30 text-red-400 text-sm">{error}</div>
      ) : (
        <>
          {/* Metrics summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="card">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-xs text-gray-400 uppercase tracking-wider">Sharpe Ratio</span>
                <InfoHint text="Rendimento corretto per il rischio: (rendimento annualizzato − tasso risk-free del 3%) ÷ volatilità annua. Calcolato sui rendimenti time-weighted (al netto di versamenti e prelievi). Indicativamente: >1 buono, >2 ottimo." />
              </div>
              <div className={`text-2xl font-bold ${metrics?.sharpe_ratio != null && metrics.sharpe_ratio > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {metrics?.sharpe_ratio != null ? fmtNum(metrics.sharpe_ratio, 2) : 'N/D'}
              </div>
            </div>
            <div className="card">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-xs text-gray-400 uppercase tracking-wider">Volatilità Annua</span>
                <InfoHint text="Oscillazione dei rendimenti: deviazione standard dei rendimenti giornalieri time-weighted, annualizzata moltiplicando per √252 (i giorni di borsa in un anno). Più è alta, più il valore del portafoglio varia." />
              </div>
              <div className="text-2xl font-bold text-gray-100">
                {metrics?.volatility_annual != null ? fmtPct(metrics.volatility_annual) : 'N/D'}
              </div>
            </div>
            <div className="card">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-xs text-gray-400 uppercase tracking-wider">Max Drawdown</span>
                <InfoHint text="Perdita massima dal picco più alto al minimo successivo, misurata sulla performance di mercato (al netto dei flussi di cassa). Indica lo scenario peggiore vissuto dal portafoglio." />
              </div>
              <div className="text-2xl font-bold text-red-400">
                {metrics?.max_drawdown != null ? fmtPct(metrics.max_drawdown) : 'N/D'}
              </div>
            </div>
            <div className="card">
              <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Rendimento 1Y</div>
              <div className={`text-2xl font-bold ${pnlClass(metrics?.period_returns?.find(r => r.period === '1Y')?.portfolio_return ?? 0)}`}>
                {metrics?.period_returns?.find(r => r.period === '1Y')?.portfolio_return != null
                  ? `${pnlSign(metrics.period_returns.find(r => r.period === '1Y')!.portfolio_return!)}${fmtPct(metrics.period_returns.find(r => r.period === '1Y')!.portfolio_return!)}`
                  : 'N/D'}
              </div>
            </div>
          </div>

          {/* Period returns — diverging bars */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Rendimenti per Periodo</h2>
            {periodReturns.length === 0 ? (
              <div className="text-gray-500 text-sm">Dati insufficienti</div>
            ) : (
              <div className="space-y-2 py-1">
                {periodReturns.map((r) => {
                  const val = r.portfolio_return
                  const pct = val != null ? (Math.abs(val) / maxAbsReturn) * 100 : 0
                  const isPos = val != null && val >= 0
                  const isNeg = val != null && val < 0
                  return (
                    <div key={r.period} className="flex items-center gap-3">
                      <span className="w-8 text-right text-xs font-semibold text-gray-400 flex-shrink-0">
                        {r.period}
                      </span>
                      <span className={`w-16 text-right text-sm font-bold tabular-nums flex-shrink-0 ${
                        val == null ? 'text-gray-600' : isPos ? 'text-emerald-400' : 'text-red-400'
                      }`}>
                        {val == null ? 'N/D' : `${pnlSign(val)}${fmtPct(val)}`}
                      </span>
                      <div className="flex-1 flex items-center h-7 gap-px min-w-0">
                        <div className="flex-1 h-full flex items-center justify-end">
                          {isNeg && (
                            <div className="h-5 bg-red-500/80 rounded-l-sm flex-shrink-0"
                                 style={{ width: `${pct}%` }} />
                          )}
                        </div>
                        <div className="w-px h-6 bg-gray-500/40 flex-shrink-0" />
                        <div className="flex-1 h-full flex items-center justify-start">
                          {isPos && (
                            <div className="h-5 bg-emerald-500/80 rounded-r-sm flex-shrink-0"
                                 style={{ width: `${pct}%` }} />
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Cumulative return chart */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Rendimento Cumulativo</h2>
            {cumulativeData.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-gray-500 text-sm">Dati insufficienti</div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={cumulativeData}>
                  <defs>
                    <linearGradient id="cumGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#D4A017" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#D4A017" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={(v) => v?.slice(5)} tick={{ fontSize: 11 }} />
                  <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v: number) => [`${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, 'Rendimento']}
                    contentStyle={tooltip()}
                  />
                  <Area type="monotone" dataKey="return_pct" stroke="#D4A017" strokeWidth={2} fill="url(#cumGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Monthly returns heatmap */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Rendimenti Mensili</h2>
            {heatYears.length === 0 ? (
              <div className="text-gray-500 text-sm">Dati insufficienti</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="text-xs w-full">
                  <thead>
                    <tr>
                      <th className="text-left text-gray-400 pr-3 py-1 w-12">Anno</th>
                      {MONTH_NAMES.map((m) => (
                        <th key={m} className="text-center text-gray-400 py-1 w-12">{m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {heatYears.map((year) => (
                      <tr key={year}>
                        <td className="pr-3 py-1 text-gray-400 font-medium">{year}</td>
                        {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => {
                          const val = heatMap[year][month]
                          return (
                            <td key={month} className="py-1 px-0.5">
                              <div
                                title={val != null ? `${val >= 0 ? '+' : ''}${val.toFixed(2)}%` : 'N/D'}
                                className="h-8 w-11 rounded flex items-center justify-center font-medium tabular-nums text-white/80 cursor-default"
                                style={{ backgroundColor: heatColor(val) }}
                              >
                                {val != null ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}` : ''}
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Drawdown chart */}
          <div className="card">
            <h2 className="text-base font-semibold text-gray-200 mb-4">Drawdown</h2>
            {drawdown.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-gray-500 text-sm">Dati insufficienti</div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={drawdown}>
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={(v) => v?.slice(5)} tick={{ fontSize: 11 }} />
                  <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
                    contentStyle={tooltip('red')}
                  />
                  <Area type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  )
}
