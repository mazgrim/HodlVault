import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { Info, Check } from 'lucide-react'
import PortfolioSelector from '../components/PortfolioSelector'
import { PageSpinner } from '../components/Spinner'
import { usePortfolios } from '../context/PortfoliosContext'
import { benchmarkApi } from '../api'
import { fmtPct, fmtNum, fmtEur, fmtAxisEur, pnlClass, pnlSign } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'

interface BenchmarkInfo { ticker: string; label: string }
interface BenchmarkHolding { instrument_id: number; ticker: string; name: string }
interface BenchmarkPoint { date: string; value: number }
interface BenchmarkSeries {
  key: string; label: string; color: string
  points: BenchmarkPoint[]
  period_return: number | null
  annualized_return: number | null
  volatility: number | null
  max_drawdown: number | null
  gain_eur: number | null
  irr: number | null
}

type Mode = 'twr' | 'invested'

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
  const [mode, setMode] = useState<Mode>('twr')
  const [available, setAvailable] = useState<BenchmarkInfo[]>([])
  const [selected, setSelected] = useState<string[]>(['SWDA.MI', 'SPY'])
  const [series, setSeries] = useState<BenchmarkSeries[]>([])
  const [holdings, setHoldings] = useState<BenchmarkHolding[]>([])
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const excludeKey = useMemo(() => [...excluded].sort((a, b) => a - b).join(','), [excluded])

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
      const ex = excludeKey ? excludeKey.split(',').map(Number) : []
      const res = await benchmarkApi.chart(selected, period, selectedPf ?? undefined, mode, ex)
      setSeries(res.data.series ?? [])
      setHoldings(res.data.holdings ?? [])
    } catch (e: any) {
      setError('Impossibile caricare i dati benchmark.')
      console.error(e?.response?.data ?? e)
    } finally {
      setLoading(false)
    }
  }, [selected, period, selectedPf, mode, excludeKey])

  // Debounced: toggling several checkboxes fires a single recompute.
  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  // Reset the what-if exclusions when switching portfolio (ids aren't comparable).
  useEffect(() => { setExcluded(new Set()) }, [selectedPf])

  const toggleBenchmark = (ticker: string) => {
    setSelected(prev =>
      prev.includes(ticker) ? prev.filter(t => t !== ticker) : [...prev, ticker]
    )
  }

  const toggleHolding = (id: number) => {
    setExcluded(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
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

      {/* Mode toggle — prominent, two clearly-labelled choices */}
      <div className="card">
        <p className="text-xs text-gray-400 uppercase tracking-wider mb-3">Modalità di confronto</p>
        <div className="flex flex-col sm:flex-row gap-2">
          {([
            ['twr', 'TWR — Rendimento di mercato', 'Base 100, indipendente dai versamenti'],
            ['invested', 'A versamenti — Guadagno reale', 'In €, con IRR: tiene conto di quando hai investito'],
          ] as const).map(([m, title, desc]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 text-left rounded-lg border px-4 py-3 transition-all ${
                mode === m
                  ? 'bg-gold-500/15 border-gold-500/50 ring-1 ring-gold-500/30'
                  : 'bg-navy-700/40 border-gray-600/40 hover:border-gray-500'
              }`}
            >
              <div className={`flex items-center gap-2 text-sm font-semibold ${mode === m ? 'text-gold-300' : 'text-gray-200'}`}>
                <span className={`flex items-center justify-center w-4 h-4 rounded-full border ${
                  mode === m ? 'border-gold-400' : 'border-gray-500'
                }`}>
                  {mode === m && <span className="w-2 h-2 rounded-full bg-gold-400" />}
                </span>
                {title}
              </div>
              <div className="text-[11px] text-gray-400 mt-1 pl-6">{desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Period selector */}
      <div className="flex gap-1 flex-wrap">
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
          {mode === 'twr' ? 'Rendimento Cumulativo (base 100)' : 'Valore nel tempo — a parità di versamenti (€)'}
        </h2>
        <p className="text-xs text-gray-500 mb-3">
          {mode === 'twr'
            ? "Tutti i valori normalizzati a 100 all'inizio del periodo — confronto diretto indipendente dalla valuta di quotazione."
            : 'Valore reale in € del tuo portafoglio confrontato con quello che avresti avuto investendo gli stessi versamenti, negli stessi giorni, nel benchmark.'}
        </p>
        <div className="flex items-start gap-1.5 mb-4 p-2.5 rounded-lg bg-navy-700/30 border border-gray-700/30">
          <Info size={13} className="mt-0.5 flex-shrink-0 text-gold-500/70" />
          {mode === 'twr' ? (
            <p className="text-xs text-gray-400 leading-relaxed">
              Il portafoglio è calcolato con il{' '}
              <span className="text-gold-400 font-medium">TWR — Time-Weighted Return</span>
              {': '}misura il rendimento puro del mercato eliminando l'effetto dei nuovi capitali investiti nel tempo.
              A differenza del semplice confronto tra valore iniziale e finale (che includerebbe i versamenti),
              il TWR calcola il rendimento di ogni sotto-periodo <em>prima</em> di ogni acquisto o vendita e li moltiplica tra loro,
              rendendo il portafoglio direttamente comparabile agli indici di riferimento.
            </p>
          ) : (
            <p className="text-xs text-gray-400 leading-relaxed">
              Confronto <span className="text-gold-400 font-medium">money-weighted</span>: i tuoi versamenti (e prelievi)
              reali vengono replicati sul benchmark alle stesse date. Le curve partono dallo stesso valore e divergono
              solo per la diversa performance. In tabella trovi il <em>guadagno in €</em> sul periodo e l'<em>IRR</em>
              {' '}(rendimento annualizzato che tiene conto di quando hai investito).
            </p>
          )}
        </div>

        {loading ? (
          <div className="h-72 flex items-center justify-center">
            <PageSpinner />
          </div>
        ) : error ? (
          <div className="h-72 flex items-center justify-center text-red-400 text-sm">{error}</div>
        ) : chartData.length === 0 ? (
          <div className="h-72 flex items-center justify-center text-center text-gray-500 text-sm px-6">
            {excluded.size > 0
              ? "La selezione non ha posizioni aperte nel periodo scelto (es. titoli già venduti). Prova un periodo più ampio o riattiva qualche titolo."
              : 'Nessun dato disponibile per il periodo selezionato'}
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
                tickFormatter={v => mode === 'twr' ? `${v.toFixed(0)}` : fmtAxisEur(v)}
                tick={{ fontSize: 10, fill: axisTick }}
                tickLine={false}
                width={mode === 'twr' ? 42 : 64}
              />
              {mode === 'twr' && <ReferenceLine y={100} stroke={grid} strokeDasharray="4 2" />}
              <Tooltip
                contentStyle={{ ...tooltip(), fontSize: 12 }}
                formatter={(v: number, name: string) => {
                  const s = series.find(s => s.key === name)
                  const label = s?.label ?? name
                  return mode === 'twr'
                    ? [`${v >= 100 ? '+' : ''}${(v - 100).toFixed(2)}%`, label]
                    : [fmtEur(v), label]
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

      {/* What-if: include/exclude holdings */}
      {holdings.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-3 gap-3">
            <p className="text-xs text-gray-400 uppercase tracking-wider">Titoli nel confronto (what-if)</p>
            <div className="flex gap-3 text-xs">
              <button
                onClick={() => setExcluded(new Set())}
                disabled={excluded.size === 0}
                className="text-gray-400 hover:text-gold-400 transition-colors disabled:opacity-40"
              >
                Tutti
              </button>
              <button
                onClick={() => setExcluded(new Set(holdings.map(h => h.instrument_id)))}
                disabled={excluded.size === holdings.length}
                className="text-gray-400 hover:text-gold-400 transition-colors disabled:opacity-40"
              >
                Nessuno
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {holdings.map(h => {
              const included = !excluded.has(h.instrument_id)
              return (
                <button
                  key={h.instrument_id}
                  onClick={() => toggleHolding(h.instrument_id)}
                  title={h.name}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                    included
                      ? 'bg-gold-500/15 border-gold-500/40 text-gold-300'
                      : 'bg-navy-700/40 border-gray-600/40 text-gray-500 line-through'
                  }`}
                >
                  <span className={`flex items-center justify-center w-3.5 h-3.5 rounded-sm border ${
                    included ? 'bg-gold-500 border-gold-500' : 'border-gray-500'
                  }`}>
                    {included && <Check size={11} className="text-[#14110a]" strokeWidth={3} />}
                  </span>
                  {h.ticker}
                </button>
              )
            })}
          </div>
          <p className="text-[11px] text-gray-500 mt-3">
            Deseleziona un titolo per vedere il confronto «come se non l'avessi mai comprato»: il grafico e l'IRR si aggiornano escludendo quel titolo e i suoi versamenti.
          </p>
        </div>
      )}

      {/* Summary table */}
      {!loading && series.length > 0 && (
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">Riepilogo</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  <th className="text-left py-2 pr-6 text-xs font-medium text-gray-400 uppercase">Nome</th>
                  {mode === 'twr' ? (
                    <>
                      <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Periodo</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Annualizzato</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Volatilità</th>
                      <th className="text-right py-2 pl-3 text-xs font-medium text-gray-400 uppercase">Max DD</th>
                    </>
                  ) : (
                    <>
                      <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Guadagno €</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-gray-400 uppercase">Rendimento</th>
                      <th className="text-right py-2 pl-3 text-xs font-medium text-gray-400 uppercase">IRR</th>
                    </>
                  )}
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
                    {mode === 'twr' ? (
                      <>
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
                      </>
                    ) : (
                      <>
                        <td className={`py-2.5 px-3 text-right tabular-nums font-semibold ${pnlClass(s.gain_eur ?? 0)}`}>
                          {s.gain_eur != null ? `${pnlSign(s.gain_eur)}${fmtEur(s.gain_eur)}` : 'N/D'}
                        </td>
                        <td className={`py-2.5 px-3 text-right tabular-nums ${pnlClass(s.period_return ?? 0)}`}>
                          {s.period_return != null ? `${s.period_return >= 0 ? '+' : ''}${fmtPct(s.period_return)}` : 'N/D'}
                        </td>
                        <td className={`py-2.5 pl-3 text-right tabular-nums ${pnlClass(s.irr ?? 0)}`}>
                          {s.irr != null ? `${s.irr >= 0 ? '+' : ''}${fmtPct(s.irr)}` : 'N/D'}
                        </td>
                      </>
                    )}
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
