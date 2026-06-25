import { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { Info } from 'lucide-react'
import PortfolioSelector from '../components/PortfolioSelector'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { benchmarkApi } from '../api'
import { fmtPct, fmtNum, pnlClass } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

interface BenchmarkInfo { ticker: string; label: string }
interface BenchmarkPoint { date: string; value: number }
interface BenchmarkSeries {
  key: string; label: string; color: string
  points: BenchmarkPoint[]
  period_return: number | null
  annualized_return: number | null
  volatility: number | null
  max_drawdown: number | null
}

const PERIODS = ['3M', '6M', 'YTD', '1A', '3A', '5A', 'Max']

// Merge separate series into a single recharts data array, forward-filling nulls
function mergeSeries(series: BenchmarkSeries[]): Record<string, any>[] {
  const dateSet = new Set<string>()
  series.forEach(s => s.points.forEach(p => dateSet.add(p.date)))
  const dates = [...dateSet].sort()

  return dates.map(date => {
    const row: Record<string, any> = { date }
    for (const s of series) {
      const pt = s.points.find(p => p.date === date)
      row[s.key] = pt?.value ?? null
    }
    return row
  })
}

export default function Benchmark() {
  const { tooltip, grid, axisTick } = useChartTheme()
  const { portfolios, loading: pfLoading } = usePortfolios()
  const [selectedPf, setSelectedPf] = useState<number | null>(null)
  const [period, setPeriod] = useState('1A')
  const [available, setAvailable] = useState<BenchmarkInfo[]>([])
  const [selected, setSelected] = useState<string[]>(['SWDA.MI', 'SPY'])
  const [series, setSeries] = useState<BenchmarkSeries[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load available benchmarks once
  useEffect(() => {
    benchmarkApi.available()
      .then(r => setAvailable(r.data))
      .catch(() => {})
  }, [])

  const load = useCallback(async () => {
    if (selected.length === 0) {
      setSeries([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await benchmarkApi.chart(selected, period, selectedPf ?? undefined)
      setSeries(res.data.series ?? [])
    } catch (e: any) {
      setError('Impossibile caricare i dati benchmark.')
      console.error(e?.response?.data ?? e)
    } finally {
      setLoading(false)
    }
  }, [selected, period, selectedPf])

  useEffect(() => { load() }, [load])

  const toggleBenchmark = (ticker: string) => {
    setSelected(prev =>
      prev.includes(ticker) ? prev.filter(t => t !== ticker) : [...prev, ticker]
    )
  }

  const chartData = mergeSeries(series)
  const portfolio = series.find(s => s.key === 'portfolio')
  const benchmarks = series.filter(s => s.key !== 'portfolio')

  if (pfLoading) return <PageSpinner />

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100">Benchmark</h1>
        <PortfolioSelector portfolios={portfolios} selected={selectedPf} onChange={setSelectedPf} />
      </div>

      {/* Benchmark selector */}
      <div className="card">
        <p className="text-xs text-gray-400 uppercase tracking-wider mb-3">Seleziona benchmark</p>
        <div className="flex flex-wrap gap-2">
          {available.map(b => {
            const active = selected.includes(b.ticker)
            return (
              <button
                key={b.ticker}
                onClick={() => toggleBenchmark(b.ticker)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                  active
                    ? 'bg-gold-500/20 border-gold-500/50 text-gold-400'
                    : 'bg-navy-700/40 border-gray-600/40 text-gray-400 hover:border-gray-500 hover:text-gray-300'
                }`}
              >
                {b.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Period selector */}
      <div className="flex gap-1">
        {PERIODS.map(p => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-all ${
              period === p
                ? 'bg-gold-500 text-[#14110a] font-bold'
                : 'bg-navy-700/50 text-gray-400 hover:text-gray-200 hover:bg-navy-700'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-1">
          Rendimento Cumulativo (base 100)
        </h2>
        <p className="text-xs text-gray-500 mb-3">
          Tutti i valori normalizzati a 100 all'inizio del periodo — confronto diretto indipendente dalla valuta di quotazione.
        </p>
        <div className="flex items-start gap-1.5 mb-4 p-2.5 rounded-lg bg-navy-700/30 border border-gray-700/30">
          <Info size={13} className="mt-0.5 flex-shrink-0 text-gold-500/70" />
          <p className="text-xs text-gray-400 leading-relaxed">
            Il portafoglio è calcolato con il{' '}
            <span className="text-gold-400 font-medium">TWR — Time-Weighted Return</span>
            {': '}misura il rendimento puro del mercato eliminando l'effetto dei nuovi capitali investiti nel tempo.
            A differenza del semplice confronto tra valore iniziale e finale (che includerebbe i versamenti),
            il TWR calcola il rendimento di ogni sotto-periodo <em>prima</em> di ogni acquisto o vendita e li moltiplica tra loro,
            rendendo il portafoglio direttamente comparabile agli indici di riferimento.
          </p>
        </div>

        {loading ? (
          <div className="h-72 flex items-center justify-center">
            <PageSpinner />
          </div>
        ) : error ? (
          <div className="h-72 flex items-center justify-center text-red-400 text-sm">{error}</div>
        ) : chartData.length === 0 ? (
          <div className="h-72 flex items-center justify-center text-gray-500 text-sm">
            Nessun dato disponibile per il periodo selezionato
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={grid} />
              <XAxis
                dataKey="date"
                tickFormatter={v => v?.slice(5)}
                tick={{ fontSize: 10, fill: axisTick }}
                tickLine={false}
              />
              <YAxis
                tickFormatter={v => `${v.toFixed(0)}`}
                tick={{ fontSize: 10, fill: axisTick }}
                tickLine={false}
                width={42}
              />
              <ReferenceLine y={100} stroke={grid} strokeDasharray="4 2" />
              <Tooltip
                contentStyle={{ ...tooltip(), fontSize: 12 }}
                formatter={(v: number, name: string) => {
                  const s = series.find(s => s.key === name)
                  return [`${v >= 100 ? '+' : ''}${(v - 100).toFixed(2)}%`, s?.label ?? name]
                }}
                labelFormatter={v => v}
              />
              {/* Portfolio line — thicker gold */}
              {series.find(s => s.key === 'portfolio') && (
                <Line
                  type="monotone"
                  dataKey="portfolio"
                  stroke="#D4A017"
                  strokeWidth={2.5}
                  dot={false}
                  connectNulls
                  name="portfolio"
                />
              )}
              {/* Benchmark lines */}
              {series.filter(s => s.key !== 'portfolio').map(s => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                  name={s.key}
                  strokeDasharray="5 3"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}

        {/* Legend */}
        {!loading && series.length > 0 && (
          <div className="flex flex-wrap gap-4 mt-3 pt-3 border-t border-gray-700/30">
            {series.map(s => (
              <div key={s.key} className="flex items-center gap-1.5">
                <div
                  className="w-6 h-0.5 rounded-full flex-shrink-0"
                  style={{
                    backgroundColor: s.color,
                    height: s.key === 'portfolio' ? 3 : 2,
                  }}
                />
                <span className="text-xs text-gray-400">{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Summary table */}
      {!loading && series.length > 0 && (
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">Riepilogo</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  <th className="text-left py-2 pr-6 text-xs font-medium text-gray-400 uppercase">Nome</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Periodo</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Annualizzato</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Volatilità</th>
                  <th className="text-right py-2 pl-3 text-xs font-medium text-gray-400 uppercase">Max DD</th>
                </tr>
              </thead>
              <tbody>
                {series.map(s => (
                  <tr key={s.key} className="border-b border-gray-700/20 table-row-hover">
                    <td className="py-2.5 pr-6">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: s.color }} />
                        <span className={`font-medium ${s.key === 'portfolio' ? 'text-gold-400' : 'text-gray-300'}`}>
                          {s.label}
                        </span>
                      </div>
                    </td>
                    <td className={`py-2.5 px-3 text-right tabular-nums font-semibold ${pnlClass(s.period_return ?? 0)}`}>
                      {s.period_return != null ? `${s.period_return >= 0 ? '+' : ''}${fmtPct(s.period_return)}` : 'N/D'}
                    </td>
                    <td className={`py-2.5 px-3 text-right tabular-nums ${pnlClass(s.annualized_return ?? 0)}`}>
                      {s.annualized_return != null ? `${s.annualized_return >= 0 ? '+' : ''}${fmtPct(s.annualized_return)}` : 'N/D'}
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums text-gray-300">
                      {s.volatility != null ? fmtPct(s.volatility) : 'N/D'}
                    </td>
                    <td className="py-2.5 pl-3 text-right tabular-nums text-red-400">
                      {s.max_drawdown != null ? fmtPct(s.max_drawdown) : 'N/D'}
                    </td>
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
