import { useState } from 'react'
import { LineChart, Line, BarChart, Bar, ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { toolsApi } from '../api'
import { fmtEur, fmtPct, fmtNum } from '../utils/format'
import { useChartTheme } from '../utils/chartTheme'
import { Calculator, Flame, BarChart2, TrendingDown } from 'lucide-react'

const TABS = [
  { id: 'compound',   label: 'Interesse Composto', icon: Calculator },
  { id: 'fire',       label: 'FIRE Calculator',    icon: Flame },
  { id: 'pac',        label: 'PAC vs Lump Sum',    icon: BarChart2 },
  { id: 'inflation',  label: 'Inflazione',         icon: TrendingDown },
] as const

type Tab = typeof TABS[number]['id']

// ── Compound ──────────────────────────────────────────────────────────────────
function CompoundTool() {
  const { tooltip, neutralSeries } = useChartTheme()
  const [form, setForm] = useState({ initial: 10000, periodic: 200, frequency: 'monthly', rate_pct: 7, years: 20, inflation_pct: 2 })
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const f = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((p) => ({ ...p, [k]: k === 'frequency' ? e.target.value : Number(e.target.value) }))

  const run = async () => {
    setLoading(true)
    try { const r = await toolsApi.compound(form); setResult(r.data) }
    finally { setLoading(false) }
  }

  const showReal = form.inflation_pct > 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {[['Capitale iniziale (€)', 'initial', 'number'], ['Versamento periodico (€)', 'periodic', 'number'],
          ['Tasso annuo (%)', 'rate_pct', 'number'], ['Anni', 'years', 'number'],
          ['Inflazione attesa (%)', 'inflation_pct', 'number']].map(([label, key, type]) => (
          <div key={key as string}>
            <label className="label">{label as string}</label>
            <input className="input" type={type as string} step={key === 'inflation_pct' || key === 'rate_pct' ? '0.1' : '1'}
              value={(form as any)[key as string]} onChange={f(key as string)} />
          </div>
        ))}
        <div>
          <label className="label">Frequenza versamento</label>
          <select className="input" value={form.frequency} onChange={f('frequency')}>
            <option value="monthly">Mensile</option>
            <option value="annual">Annuale</option>
          </select>
        </div>
      </div>
      <p className="text-xs text-gray-500">Imposta l'inflazione a 0 per vedere solo il valore nominale.</p>
      <button onClick={run} disabled={loading} className="btn-primary">{loading ? '...' : 'Calcola'}</button>

      {result && (
        <div className="space-y-4">
          <div className={`grid grid-cols-1 gap-3 ${showReal ? 'sm:grid-cols-4' : 'sm:grid-cols-3'}`}>
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Valore Finale</div>
              <div className="text-xl font-bold text-gold-500">{fmtEur(result.final_value)}</div>
            </div>
            {showReal && (
              <div className="card text-center">
                <div className="flex items-center justify-center gap-1 text-xs text-gray-400 mb-1">
                  Valore Reale
                  <span className="text-[10px] text-gray-500">(oggi)</span>
                </div>
                <div className="text-xl font-bold text-sky-400">{fmtEur(result.real_final_value)}</div>
              </div>
            )}
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Capitale Investito</div>
              <div className="text-xl font-bold text-gray-100">{fmtEur(result.total_invested)}</div>
            </div>
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Guadagno</div>
              <div className="text-xl font-bold text-emerald-400">{fmtEur(result.total_gains)}</div>
            </div>
          </div>
          {showReal && (
            <p className="text-xs text-gray-500">
              Con un'inflazione del {fmtNum(form.inflation_pct, 1)}%, i {fmtEur(result.final_value)} nominali
              equivalgono a {fmtEur(result.real_final_value)} di potere d'acquisto di oggi.
            </p>
          )}
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={result.rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => `€${(v/1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number, n) => [fmtEur(v),
                n === 'value' ? 'Valore nominale' : n === 'real_value' ? 'Valore reale' : 'Investito']}
                contentStyle={tooltip()} />
              <Bar dataKey="invested" fill={neutralSeries} name="invested" radius={[0,0,0,0]} />
              <Bar dataKey="value" fill="#D4A017" name="value" radius={[4,4,0,0]} />
              {showReal && (
                <Line type="monotone" dataKey="real_value" name="real_value" stroke="#38bdf8"
                  strokeWidth={2} strokeDasharray="5 4" dot={false} />
              )}
              <Legend formatter={(v) => v === 'value' ? 'Valore nominale' : v === 'real_value' ? 'Valore reale (oggi)' : 'Investito'} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ── FIRE Calculator (ispirato a The Bull) ────────────────────────────────────
function FireTool() {
  const { tooltip, grid, neutralSeries } = useChartTheme()
  // § 1 — Spese & SWR
  const [expenses, setExpenses] = useState([
    { id: 1, label: 'Affitto / Mutuo', amount: 800 },
    { id: 2, label: 'Spese correnti',  amount: 500 },
  ])
  const [swrMult, setSwrMult] = useState(300)

  // § 2 — Coast FIRE
  const [coastForm, setCoastForm] = useState({
    currentAssets: 50000, currentAge: 30, targetAge: 50, realReturn: 5,
  })
  // § 2 — Anni al FIRE
  const [firePathForm, setFirePathForm] = useState({
    currentAssets: 50000, monthlySavings: 200, expectedReturn: 5,
  })

  // § 3 — Correzione fiscale
  const [taxForm, setTaxForm] = useState({ capitalGainsPct: 50, assets26Pct: 80 })

  // § 4 — Monte Carlo
  const [mcForm, setMcForm] = useState({ avgReturn: 7, volatility: 15, years: 30 })
  const [mcResult, setMcResult] = useState<any>(null)

  // ── Derived ──────────────────────────────────────────────────────────────────
  const monthlyTotal  = expenses.reduce((s, e) => s + (e.amount || 0), 0)
  const annualExpenses = monthlyTotal * 12
  const fireNumber    = monthlyTotal * swrMult

  const swrOptions = [
    { mult: 240, desc: '5% — Ottimistico' },
    { mult: 300, desc: '4% — Standard USA' },
    { mult: 333, desc: '3.6% — Morningstar' },
    { mult: 360, desc: '3.3% — Prudente' },
    { mult: 400, desc: '3% — Europa/FIRE lungo' },
  ]

  const assets12Pct    = 100 - taxForm.assets26Pct
  const effectiveTax   = (taxForm.assets26Pct * 0.26 + assets12Pct * 0.125) / 100 * (taxForm.capitalGainsPct / 100)
  const grossFireNum   = fireNumber / (1 - effectiveTax)
  const taxPremium     = grossFireNum - fireNumber

  const swrScenarios = swrOptions.map(o => ({
    ...o,
    net: monthlyTotal * o.mult,
    gross: (monthlyTotal * o.mult) / (1 - effectiveTax),
  }))

  // § 2a — Coast FIRE
  const { currentAge, targetAge, realReturn, currentAssets: coastAssets } = coastForm
  const yearsToTarget = Math.max(0, targetAge - currentAge)
  const coastFireNum  = fireNumber / Math.pow(1 + realReturn / 100, yearsToTarget)
  const hasCoast      = coastAssets >= coastFireNum

  // § 2b — Anni al FIRE (formula logaritmica esatta)
  const { currentAssets: fpAssets, monthlySavings, expectedReturn } = firePathForm
  // Geometric monthly rate so that compounding 12 months equals the annual rate.
  // The same r_m drives both the closed-form formula and the projection chart.
  const r_m = Math.pow(1 + expectedReturn / 100, 1 / 12) - 1
  const monthsToFire = r_m > 0
    ? Math.log((fireNumber + monthlySavings / r_m) / (fpAssets + monthlySavings / r_m)) / Math.log(1 + r_m)
    : monthlySavings > 0 ? (fireNumber - fpAssets) / monthlySavings : Infinity
  const yearsToFire = monthsToFire / 12
  const fireYear    = new Date().getFullYear() + Math.ceil(yearsToFire)
  const chartYears  = Math.min(Math.ceil(yearsToFire) + 2, 60)
  const portfolioRows = (() => {
    const rows = []
    let w = fpAssets
    for (let y = 0; y <= chartYears; y++) {
      rows.push({ year: new Date().getFullYear() + y, wealth: Math.round(w), target: Math.round(fireNumber), contributed: Math.round(fpAssets + monthlySavings * 12 * y) })
      if (y < chartYears) for (let m = 0; m < 12; m++) w = w * (1 + r_m) + monthlySavings
    }
    return rows
  })()

  // § 4 Monte Carlo (Box-Muller)
  function runMonteCarlo() {
    const start  = Math.round(grossFireNum) || fireNumber
    const avgR   = mcForm.avgReturn  / 100
    const vol    = mcForm.volatility / 100
    const N      = 1000
    const Y      = mcForm.years
    const paths: number[][] = []
    let failCount = 0, totalFailYear = 0
    for (let i = 0; i < N; i++) {
      let p = start; const path = [p]; let failed = false; let fy = 0
      for (let y = 1; y <= Y; y++) {
        // Once a path is depleted it stays at 0 — wealth can't go negative.
        if (failed) { path.push(0); continue }
        const u1 = Math.max(Math.random(), 1e-12), u2 = Math.random()
        const z  = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2)
        p = p * (1 + avgR + vol * z) - annualExpenses
        if (p <= 0) { failed = true; fy = y; p = 0 }
        path.push(p)
      }
      if (failed) { failCount++; totalFailYear += fy }
      paths.push(path)
    }
    const chart = Array.from({ length: Y + 1 }, (_, y) => {
      const vals = paths.map(p => p[y]).sort((a, b) => a - b)
      const pct  = (q: number) => vals[Math.floor(q * N / 100)]
      return { year: y, p10: pct(10), p25: pct(25), p50: pct(50), p75: pct(75), p90: pct(90) }
    })
    setMcResult({ successPct: ((N - failCount) / N * 100).toFixed(1), successCount: N - failCount, failCount, avgFailYear: failCount > 0 ? (totalFailYear / failCount).toFixed(1) : 'N/A', chart })
  }

  // ── Expense helpers ───────────────────────────────────────────────────────────
  const addExp    = () => setExpenses(p => [...p, { id: Date.now(), label: '', amount: 0 }])
  const removeExp = (id: number) => setExpenses(p => p.filter(e => e.id !== id))
  const updExp    = (id: number, field: 'label' | 'amount', val: string | number) =>
    setExpenses(p => p.map(e => e.id === id ? { ...e, [field]: val } : e))

  return (
    <div className="space-y-8">

      {/* ── Intro ───────────────────────────────────────────────────────────── */}
      <div className="text-xs text-gray-400 leading-relaxed bg-navy-800/60 border border-gray-700/40 rounded-lg p-3 space-y-1.5">
        <p>
          Il movimento <span className="text-gold-400 font-medium">FIRE</span> (Financial Independence, Retire Early)
          punta ad accumulare un capitale che, investito, copra le tue spese senza bisogno di lavorare.
          Questo strumento ti guida in 5 passi:
        </p>
        <p>
          <span className="text-gray-300">①</span> quanto ti serve (FIRE Number) ·
          <span className="text-gray-300"> ②</span> se sei già a metà strada (Coast FIRE) ·
          <span className="text-gray-300"> ③</span> fra quanti anni ci arrivi ·
          <span className="text-gray-300"> ④</span> quanto incide il fisco italiano ·
          <span className="text-gray-300"> ⑤</span> quanto è solido il piano (Monte Carlo).
        </p>
        <p className="text-gray-600">Tutti i calcoli sono indicativi e non costituiscono consulenza finanziaria.</p>
      </div>

      {/* ── § 1 Spese mensili & FIRE Number ─────────────────────────────────── */}
      <div>
        <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
          <span className="text-gold-500">①</span> Spese Mensili &amp; FIRE Number
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Il FIRE Number è il capitale che ti rende indipendente: spese annue moltiplicate per l'inverso del
          Safe Withdrawal Rate (SWR), il tasso che puoi prelevare ogni anno senza esaurire il capitale.
          Es. con SWR 4% servono 25× le spese annue. Scegli lo scenario SWR nella tabella sotto.
        </p>

        <div className="space-y-2 mb-2">
          <div className="hidden sm:grid grid-cols-[minmax(0,1fr)_9rem_10rem_1.5rem] gap-2 px-1">
            <span className="text-xs text-gray-600">Voce</span>
            <span className="text-xs text-gray-600 text-right">Mensile</span>
            <span className="text-xs text-gray-600 text-right">FIRE target</span>
            <span />
          </div>
          {expenses.map(e => (
            <div key={e.id} className="grid grid-cols-[minmax(0,1fr)_7rem_1.5rem] sm:grid-cols-[minmax(0,1fr)_9rem_10rem_1.5rem] gap-2 items-center">
              <input className="input min-w-0" placeholder="Voce di spesa" value={e.label}
                onChange={ev => updExp(e.id, 'label', ev.target.value)} />
              <div className="relative">
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 text-sm">€</span>
                <input className="input pl-5 text-right min-w-0 w-full" type="number" placeholder="0" value={e.amount || ''}
                  onChange={ev => updExp(e.id, 'amount', Number(ev.target.value))} />
              </div>
              <div className="hidden sm:block text-right text-xs font-semibold text-gold-500/80 bg-gold-500/5 border border-gold-500/15 rounded-lg px-2 py-2 tabular-nums truncate">
                {e.amount ? fmtEur(e.amount * swrMult) : '—'}
              </div>
              <button onClick={() => removeExp(e.id)} className="text-gray-600 hover:text-red-400 text-lg leading-none">×</button>
            </div>
          ))}
        </div>
        <button onClick={addExp} className="text-sm text-gold-500 hover:text-gold-400 mb-4">+ Aggiungi voce</button>

        <div className="flex items-center justify-between mb-3 px-1">
          <span className="text-sm text-gray-400">Totale mensile</span>
          <span className="text-2xl font-bold text-gold-500">{fmtEur(monthlyTotal)}</span>
        </div>

        {/* SWR toggles */}
        <div className="flex flex-wrap gap-2 mb-4">
          {swrOptions.map(o => (
            <button key={o.mult} onClick={() => setSwrMult(o.mult)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-all border ${
                swrMult === o.mult
                  ? 'bg-gold-500/20 text-gold-500 border-gold-500/40'
                  : 'text-gray-400 border-gray-700 hover:border-gray-500'
              }`}>
              ×{o.mult} <span className="opacity-60 ml-1">{o.desc.split('—')[0].trim()}</span>
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          <div className="card-gold text-center">
            <div className="text-xs text-gray-400 mb-1">FIRE Number (netto)</div>
            <div className="text-2xl font-black text-gold-500">{fmtEur(fireNumber)}</div>
            <div className="text-xs text-gray-500 mt-1">SWR {(12 / swrMult * 100).toFixed(1)}% · ×{swrMult}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Prelievo mensile sostenibile</div>
            <div className="text-xl font-bold text-gray-100">{fmtEur(monthlyTotal)}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Spese annue</div>
            <div className="text-xl font-bold text-gray-100">{fmtEur(annualExpenses)}</div>
          </div>
        </div>

        <table className="w-full text-xs text-gray-400">
          <thead><tr className="border-b border-gray-700">
            <th className="text-left py-2">Scenario</th>
            <th className="text-right py-2">SWR</th>
            <th className="text-right py-2">FIRE Number (netto)</th>
          </tr></thead>
          <tbody>
            {swrScenarios.map(s => (
              <tr key={s.mult} className={`border-b border-gray-800/60 ${s.mult === swrMult ? 'text-gold-400 font-semibold' : ''}`}>
                <td className="py-1.5">{s.desc}</td>
                <td className="text-right">{(12 / s.mult * 100).toFixed(1)}%</td>
                <td className="text-right">{fmtEur(s.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── § 2a Coast FIRE ──────────────────────────────────────────────────── */}
      <div className="border-t border-gray-700/50 pt-6">
        <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
          <span className="text-gold-500">②</span> Coast FIRE — Hai già raggiunto la libertà intermedia?
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Il Coast FIRE Number è il capitale che, investito oggi senza ulteriori contributi, crescerà fino al tuo FIRE Number entro l'età target.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {([
            ['Patrimonio attuale (€)', 'currentAssets', 1000],
            ['Età attuale',           'currentAge',    1],
            ['Età target FIRE',       'targetAge',     1],
            ['Rendimento reale (%)',  'realReturn',    0.5],
          ] as [string, keyof typeof coastForm, number][]).map(([lbl, key, step]) => (
            <div key={key}>
              <label className="label">{lbl}</label>
              <input className="input" type="number" step={step} value={coastForm[key]}
                onChange={e => setCoastForm(p => ({ ...p, [key]: Number(e.target.value) }))} />
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <div className={`card text-center border ${hasCoast ? 'border-emerald-500/40' : 'border-gray-700'}`}>
            <div className="text-xs text-gray-400 mb-1">Coast FIRE Number</div>
            <div className="text-xl font-bold text-gray-100">{fmtEur(Math.round(coastFireNum))}</div>
            <div className="text-xs text-gray-500 mt-1">da investire oggi senza contribuire</div>
          </div>
          <div className={`card text-center border ${hasCoast ? 'border-emerald-500/40' : 'border-gray-700'}`}>
            <div className="text-xs text-gray-400 mb-1">Patrimonio attuale</div>
            <div className={`text-xl font-bold ${hasCoast ? 'text-emerald-400' : 'text-gray-300'}`}>{fmtEur(coastAssets)}</div>
          </div>
          <div className={`card text-center border col-span-2 sm:col-span-1 ${hasCoast ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-orange-500/30 bg-orange-500/5'}`}>
            <div className="text-xs text-gray-400 mb-1">Stato</div>
            <div className={`text-base font-bold ${hasCoast ? 'text-emerald-400' : 'text-orange-400'}`}>
              {hasCoast ? '✓ Coast FIRE raggiunto!' : `Mancano ${fmtEur(Math.round(coastFireNum - coastAssets))}`}
            </div>
            <div className="text-xs text-gray-500 mt-1">target età {targetAge}</div>
          </div>
        </div>
      </div>

      {/* ── § 2b Anni al FIRE ────────────────────────────────────────────────── */}
      <div className="border-t border-gray-700/50 pt-6">
        <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
          <span className="text-gold-500">③</span> Quanti anni mancano al tuo FIRE?
        </h3>
        <p className="text-xs text-gray-500 mb-1">
          Stima fra quanti anni raggiungi il FIRE Number, partendo dal patrimonio già investito, dal risparmio che
          investi ogni mese e dal rendimento annuo atteso. Il grafico mostra la crescita del patrimonio rispetto ai
          soli contributi e al target.
        </p>
        <p className="text-xs text-gray-600 mb-3">
          Formula: n = log[(FIRE + PMT/r) ÷ (Patrimonio + PMT/r)] ÷ log(1 + r), dove r = rendimento mensile
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          {([
            ['Patrimonio investito (€)',       'currentAssets',  1000],
            ['Risparmio mensile che investi (€)', 'monthlySavings', 50],
            ['Rendimento annuo atteso (%)',    'expectedReturn', 0.5],
          ] as [string, keyof typeof firePathForm, number][]).map(([lbl, key, step]) => (
            <div key={key}>
              <label className="label">{lbl}</label>
              <input className="input" type="number" step={step} value={firePathForm[key]}
                onChange={e => setFirePathForm(p => ({ ...p, [key]: Number(e.target.value) }))} />
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="card-gold text-center">
            <div className="text-xs text-gray-400 mb-1">Anni al FIRE</div>
            <div className="text-3xl font-black text-gold-500">
              {isFinite(yearsToFire) && yearsToFire > 0 ? yearsToFire.toFixed(1) : '—'}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {isFinite(monthsToFire) && monthsToFire > 0 ? `${Math.round(monthsToFire)} mesi · Anno ${fireYear}` : 'già raggiunto'}
            </div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Anno obiettivo</div>
            <div className="text-xl font-bold text-gray-100">{isFinite(fireYear) ? fireYear : '—'}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Patrimonio proiettato</div>
            <div className="text-xl font-bold text-emerald-400">{fmtEur(portfolioRows[portfolioRows.length - 1]?.wealth ?? 0)}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">FIRE Target</div>
            <div className="text-xl font-bold text-red-400">{fmtEur(fireNumber)}</div>
          </div>
        </div>

        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={portfolioRows}>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} />
            <XAxis dataKey="year" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={v => `€${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number, n) => [fmtEur(v), n === 'wealth' ? 'Patrimonio' : n === 'target' ? 'Target FIRE' : 'Contributi']}
              contentStyle={tooltip()} />
            <Line type="monotone" dataKey="contributed" stroke={neutralSeries} strokeWidth={1.5} dot={false} name="contributed" strokeDasharray="2 2" />
            <Line type="monotone" dataKey="wealth"      stroke="#D4A017" strokeWidth={2}   dot={false} name="wealth" />
            <Line type="monotone" dataKey="target"      stroke="#ef4444" strokeWidth={1.5} dot={false} name="target" strokeDasharray="4 4" />
            <Legend formatter={v => v === 'wealth' ? 'Patrimonio' : v === 'target' ? 'Target FIRE' : 'Contributi'} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── § 4 Correzione fiscale ────────────────────────────────────────────── */}
      <div className="border-t border-gray-700/50 pt-6">
        <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
          <span className="text-gold-500">④</span> Correzione Fiscale (Italia)
        </h3>
        <p className="text-xs text-gray-500 mb-3">Calcola il FIRE Number lordo tenendo conto della tassazione italiana sulle plusvalenze.</p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          <div>
            <label className="label">Plusvalenze sul portafoglio (%)</label>
            <input className="input" type="number" step="1" min="0" max="100" value={taxForm.capitalGainsPct}
              onChange={e => setTaxForm(p => ({ ...p, capitalGainsPct: Number(e.target.value) }))} />
            <p className="text-xs text-gray-600 mt-1">&lt;10 anni: 40–50% · 15–25 anni: 55–65% · &gt;25 anni: &gt;65%</p>
          </div>
          <div>
            <label className="label">Asset tassati al 26% (%)</label>
            <input className="input" type="number" step="1" min="0" max="100" value={taxForm.assets26Pct}
              onChange={e => setTaxForm(p => ({ ...p, assets26Pct: Number(e.target.value) }))} />
            <p className="text-xs text-gray-600 mt-1">ETF azionari, obbligazionari corporativi</p>
          </div>
          <div>
            <label className="label">Asset tassati al 12.5% (%)</label>
            <input className="input bg-gray-800/50 text-gray-400" type="number" readOnly value={assets12Pct} />
            <p className="text-xs text-gray-600 mt-1">BTP, titoli di stato white-list · calcolato automaticamente</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Aliquota effettiva</div>
            <div className="text-xl font-bold text-orange-400">{(effectiveTax * 100).toFixed(2)}%</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">FIRE Number (lordo)</div>
            <div className="text-xl font-bold text-gold-500">{fmtEur(Math.round(grossFireNum))}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">Premio fiscale</div>
            <div className="text-xl font-bold text-red-400">{fmtEur(Math.round(taxPremium))}</div>
          </div>
          <div className="card text-center">
            <div className="text-xs text-gray-400 mb-1">FIRE Number (netto)</div>
            <div className="text-xl font-bold text-gray-300">{fmtEur(fireNumber)}</div>
          </div>
        </div>

        <table className="w-full text-xs text-gray-400">
          <thead><tr className="border-b border-gray-700">
            <th className="text-left py-2">Scenario</th>
            <th className="text-right py-2">FIRE Netto</th>
            <th className="text-right py-2">FIRE Lordo</th>
            <th className="text-right py-2">Premio</th>
          </tr></thead>
          <tbody>
            {swrScenarios.map(s => (
              <tr key={s.mult} className={`border-b border-gray-800/60 ${s.mult === swrMult ? 'text-gold-400 font-semibold' : ''}`}>
                <td className="py-1.5">{s.desc}</td>
                <td className="text-right">{fmtEur(s.net)}</td>
                <td className="text-right">{fmtEur(Math.round(s.gross))}</td>
                <td className="text-right text-red-400">{fmtEur(Math.round(s.gross - s.net))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── § 5 Monte Carlo ───────────────────────────────────────────────────── */}
      <div className="border-t border-gray-700/50 pt-6">
        <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
          <span className="text-gold-500">⑤</span> Simulazione Monte Carlo
        </h3>
        <div className="text-xs text-gray-500 mb-4 space-y-1.5 bg-navy-800/60 border border-gray-700/40 rounded-lg p-3">
          <p>La simulazione genera <span className="text-gray-300 font-medium">1.000 possibili sequenze di rendimenti annuali</span> usando la distribuzione normale con la media e la deviazione standard indicate. Ogni anno il portafoglio cresce del rendimento casuale e decresce del prelievo annuale (spese annue al SWR scelto).</p>
          <p>Il grafico mostra la <span className="text-gray-300 font-medium">distribuzione degli esiti possibili</span>, non una previsione. I rendimenti sono generati con il metodo <span className="text-gray-300 font-medium">Box-Muller</span> per l'approssimazione della distribuzione normale.</p>
          <p className="text-gray-600">Basato su Trinity Study (1998), Bengen (1994) e Morningstar Research.</p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div>
            <label className="label">Portafoglio al FIRE (€)</label>
            <input className="input bg-gray-800/50" type="number" readOnly value={Math.round(grossFireNum) || fireNumber} />
          </div>
          <div>
            <label className="label">Rendimento medio (%)</label>
            <input className="input" type="number" step="0.5" value={mcForm.avgReturn}
              onChange={e => setMcForm(p => ({ ...p, avgReturn: Number(e.target.value) }))} />
          </div>
          <div>
            <label className="label">Volatilità (%)</label>
            <input className="input" type="number" step="1" value={mcForm.volatility}
              onChange={e => setMcForm(p => ({ ...p, volatility: Number(e.target.value) }))} />
          </div>
          <div>
            <label className="label">Durata</label>
            <div className="flex gap-2 mt-1">
              {[30, 40].map(y => (
                <button key={y} onClick={() => setMcForm(p => ({ ...p, years: y }))}
                  className={`flex-1 py-1.5 rounded text-sm font-medium border transition-all ${
                    mcForm.years === y ? 'bg-gold-500/20 text-gold-500 border-gold-500/40' : 'text-gray-400 border-gray-700'
                  }`}>{y} anni</button>
              ))}
            </div>
          </div>
        </div>

        <button onClick={runMonteCarlo} className="btn-primary mb-4">Esegui simulazione</button>

        {mcResult && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="card text-center">
                <div className="text-xs text-gray-400 mb-1">Probabilità successo</div>
                <div className={`text-3xl font-black ${Number(mcResult.successPct) >= 90 ? 'text-emerald-400' : Number(mcResult.successPct) >= 70 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {mcResult.successPct}%
                </div>
              </div>
              <div className="card text-center">
                <div className="text-xs text-gray-400 mb-1">Simulazioni ok</div>
                <div className="text-xl font-bold text-emerald-400">{mcResult.successCount}</div>
              </div>
              <div className="card text-center">
                <div className="text-xs text-gray-400 mb-1">Simulazioni fallite</div>
                <div className="text-xl font-bold text-red-400">{mcResult.failCount}</div>
              </div>
              <div className="card text-center">
                <div className="text-xs text-gray-400 mb-1">Anno medio fallimento</div>
                <div className="text-xl font-bold text-gray-300">{mcResult.avgFailYear}</div>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={mcResult.chart}>
                <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} label={{ value: 'Anni dal FIRE', position: 'insideBottomRight', offset: -10, fontSize: 10 }} />
                <YAxis tickFormatter={v => `€${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number, n) => [fmtEur(Math.round(v)), String(n)]}
                  contentStyle={tooltip()} />
                <Line type="monotone" dataKey="p90" stroke="#10b981" strokeWidth={1}   dot={false} name="P90 (ottimistico)" strokeOpacity={0.8} />
                <Line type="monotone" dataKey="p75" stroke="#60a5fa" strokeWidth={1.5} dot={false} name="P75" strokeOpacity={0.8} />
                <Line type="monotone" dataKey="p50" stroke="#D4A017" strokeWidth={2.5} dot={false} name="P50 (mediana)" />
                <Line type="monotone" dataKey="p25" stroke="#f97316" strokeWidth={1.5} dot={false} name="P25" strokeOpacity={0.8} />
                <Line type="monotone" dataKey="p10" stroke="#ef4444" strokeWidth={1}   dot={false} name="P10 (pessimistico)" strokeOpacity={0.8} />
                <Legend />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* ── Fonte ──────────────────────────────────────────────────────────────── */}
      <div className="border-t border-gray-700/30 pt-3">
        <p className="text-xs text-gray-600">
          Metodologia ispirata a{' '}
          <span className="text-gold-500/70">The Bull — FIRE Calculator</span>.{' '}
          Calcolatore standalone: nessun dato viene trasmesso a server esterni.
        </p>
      </div>
    </div>
  )
}

// ── PAC vs Lump Sum ───────────────────────────────────────────────────────────
const PAC_FREQUENCIES = [
  { value: 'monthly',    label: 'Mensile' },
  { value: 'quarterly',  label: 'Trimestrale' },
  { value: 'semiannual', label: 'Semestrale' },
  { value: 'annual',     label: 'Annuale' },
] as const

function PacTool() {
  const { tooltip } = useChartTheme()
  const [form, setForm] = useState({ total_amount: 100000, years: 10, expected_return_pct: 7, frequency: 'monthly' })
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const f = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((p) => ({ ...p, [k]: k === 'frequency' ? e.target.value : Number(e.target.value) }))

  const run = async () => {
    setLoading(true)
    try { const r = await toolsApi.pacVsLumpsum(form); setResult(r.data) }
    finally { setLoading(false) }
  }

  const freqLabel = PAC_FREQUENCIES.find((x) => x.value === form.frequency)?.label ?? 'Mensile'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[['Importo totale (€)', 'total_amount'], ['Anni', 'years'], ['Rendimento atteso (%)', 'expected_return_pct']].map(([label, key]) => (
          <div key={key}>
            <label className="label">{label}</label>
            <input className="input" type="number" value={(form as any)[key]} onChange={f(key)} step="0.1" />
          </div>
        ))}
        <div>
          <label className="label">Frequenza PAC</label>
          <select className="input" value={form.frequency} onChange={f('frequency')}>
            {PAC_FREQUENCIES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
      <button onClick={run} disabled={loading} className="btn-primary">{loading ? '...' : 'Confronta'}</button>

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="card">
              <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">Lump Sum (investimento unico)</div>
              <div className="text-2xl font-bold text-gold-500">{fmtEur(result.lump_sum_final)}</div>
              <div className="text-sm text-gray-400 mt-1">+{fmtPct(result.lump_sum_return_total_pct)} totale · CAGR {fmtPct(result.lump_sum_cagr_pct)}</div>
            </div>
            <div className="card">
              <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">PAC {freqLabel}</div>
              <div className="text-2xl font-bold text-emerald-400">{fmtEur(result.pac_final)}</div>
              <div className="text-sm text-gray-400 mt-1">+{fmtPct(result.pac_return_total_pct)} totale · CAGR {fmtPct(result.pac_cagr_pct)}</div>
              {result.num_contributions != null && (
                <div className="text-xs text-gray-500 mt-1.5">
                  {result.num_contributions} versamenti da {fmtEur(result.contribution_amount)}
                </div>
              )}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={result.chart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => `€${(v/1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => [fmtEur(v)]}
                contentStyle={tooltip()} />
              <Line type="monotone" dataKey="lump_sum" stroke="#D4A017" strokeWidth={2} dot={false} name="Lump Sum" />
              <Line type="monotone" dataKey="pac" stroke="#10b981" strokeWidth={2} dot={false} name="PAC" />
              <Legend />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ── Inflation ─────────────────────────────────────────────────────────────────
function InflationTool() {
  const { tooltip } = useChartTheme()
  const [form, setForm] = useState({ amount: 10000, start_year: 2000, end_year: new Date().getFullYear(), inflation_pct: 2 })
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const f = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((p) => ({ ...p, [k]: Number(e.target.value) }))

  const run = async () => {
    setLoading(true)
    try { const r = await toolsApi.inflation(form); setResult(r.data) }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[['Importo (€)', 'amount'], ['Anno di partenza', 'start_year'], ['Anno di arrivo', 'end_year'], ['Inflazione media (%)', 'inflation_pct']].map(([label, key]) => (
          <div key={key}>
            <label className="label">{label}</label>
            <input className="input" type="number" value={(form as any)[key]} onChange={f(key)} step={key === 'inflation_pct' ? '0.1' : '1'} />
          </div>
        ))}
      </div>
      <button onClick={run} disabled={loading} className="btn-primary">{loading ? '...' : 'Calcola'}</button>

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Valore Nominale</div>
              <div className="text-2xl font-bold text-gray-100">{fmtEur(form.amount)}</div>
            </div>
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Valore Reale ({form.end_year})</div>
              <div className="text-2xl font-bold text-red-400">{fmtEur(result.real_value)}</div>
            </div>
            <div className="card text-center">
              <div className="text-xs text-gray-400 mb-1">Potere d'acquisto perso</div>
              <div className="text-2xl font-bold text-red-400">{fmtPct(result.purchasing_power_lost_pct)}</div>
            </div>
            <div className="card text-center border-gold-500/40">
              <div className="flex items-center justify-center gap-1 text-xs text-gray-400 mb-1">
                Valore necessario ({form.end_year})
              </div>
              <div className="text-2xl font-bold text-gold-500">{fmtEur(result.required_value)}</div>
              <div className="text-[10px] text-gray-500 mt-1">per mantenere il potere d'acquisto</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={result.chart.filter((_: any, i: number) => i % Math.ceil(result.chart.length / 20) === 0)}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => `€${(v/1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => [fmtEur(v), 'Potere d\'acquisto']}
                contentStyle={tooltip('red')} />
              <Bar dataKey="value" fill="#ef4444" radius={[2,2,0,0]} name="Valore reale" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Tools() {
  const [activeTab, setActiveTab] = useState<Tab>('compound')

  const content: Record<Tab, React.ReactNode> = {
    compound: <CompoundTool />,
    fire: <FireTool />,
    pac: <PacTool />,
    inflation: <InflationTool />,
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Tools Finanziari</h1>
      <p className="text-gray-400 text-sm -mt-2">Calcolatori standalone — nessun dato utente richiesto</p>

      <div className="flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === id
                ? 'bg-gold-500/20 text-gold-500 border border-gold-500/30'
                : 'text-gray-400 hover:text-gray-200 bg-navy-800 border border-gray-700/40'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      <div className="card">
        {content[activeTab]}
      </div>
    </div>
  )
}
