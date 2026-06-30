import { useState, useRef } from 'react'
import { Upload, CheckCircle, AlertCircle, FileText, Plus, Info } from 'lucide-react'
import { usePortfolios } from '../context/PortfoliosContext'
import { importApi, portfolioApi } from '../api'
import { fmtDate, fmtNum } from '../utils/format'
import TickerSearchInput from '../components/TickerSearchInput'

interface ParsedRow {
  date: string
  type: string
  ticker: string | null
  isin: string | null
  name: string | null
  quantity: number
  price: number
  fees: number
  currency: string
  duplicate: boolean
  is_dividend: boolean
}

interface Preview { total: number; duplicates: number }

const BROKERS = ['Fineco', 'Directa', 'Trade Republic']

// Istruzioni su dove esportare i file, per broker (mostrate in base alla selezione).
const EXPORT_HELP: Record<string, { title: string; steps: string }[]> = {
  Fineco: [
    {
      title: 'Movimenti conto',
      steps: 'Sezione Account → movimenti, seleziona il periodo desiderato, poi "Esporta in Excel" (in basso a destra).',
    },
    {
      title: 'Ordini e contabili',
      steps: 'Sezione Account → menu "Ordini e contabili", seleziona il periodo desiderato, poi "Esporta in Excel" (in basso a sinistra).',
    },
  ],
}

function typeBadge(row: ParsedRow) {
  if (row.is_dividend)
    return <span className="badge bg-purple-900/40 text-purple-300 border border-purple-700/30">DIV</span>
  if (row.type === 'BUY')
    return <span className="badge-green">BUY</span>
  return <span className="badge-red">SELL</span>
}

export default function Import() {
  const { portfolios, reload: reloadPortfolios } = usePortfolios()
  const [broker, setBroker] = useState(BROKERS[0])
  const [portfolioId, setPortfolioId] = useState<number | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [rows, setRows] = useState<ParsedRow[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [step, setStep] = useState<'upload' | 'preview' | 'done'>('upload')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ imported: number; skipped: number; no_ticker: number } | null>(null)
  const [includeDuplicates, setIncludeDuplicates] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // Inline portfolio creation
  const [showNewPf, setShowNewPf] = useState(false)
  const [newPfName, setNewPfName] = useState('')
  const [newPfBroker, setNewPfBroker] = useState('')
  const [creatingPf, setCreatingPf] = useState(false)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) setFile(f)
    setPreview(null)
    setRows([])
    setError('')
  }

  const handleCreatePortfolio = async () => {
    if (!newPfName.trim()) return
    setCreatingPf(true)
    try {
      const res = await portfolioApi.create({ name: newPfName.trim(), broker: newPfBroker.trim() || undefined })
      await reloadPortfolios()
      setPortfolioId(res.data.id)
      setShowNewPf(false)
      setNewPfName('')
      setNewPfBroker('')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore nella creazione del portafoglio')
    } finally {
      setCreatingPf(false)
    }
  }

  const handlePreview = async () => {
    if (!file || !portfolioId) {
      setError('Seleziona un file e un portafoglio')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await importApi.preview(file, broker.toLowerCase().replace(' ', '_'), portfolioId)
      setRows(res.data.rows)
      setPreview({ total: res.data.total, duplicates: res.data.duplicates })
      setStep('preview')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore nel parsing del file')
    } finally {
      setLoading(false)
    }
  }

  const handleTickerChange = (idx: number, value: string) => {
    const newTicker = value.toUpperCase() || null
    setRows(prev => {
      const src = prev[idx]
      return prev.map((r, i) => {
        if (i === idx) return { ...r, ticker: newTicker }
        // Auto-propagate to other rows that represent the same instrument
        const sameIsin = src.isin && r.isin && src.isin === r.isin
        const sameName = !src.isin && !r.isin && src.name && r.name && src.name === r.name
        if (sameIsin || sameName) return { ...r, ticker: newTicker }
        return r
      })
    })
  }

  const handleImport = async () => {
    if (!preview || !portfolioId) return
    setLoading(true)
    setError('')
    try {
      const toImport = includeDuplicates ? rows : rows.filter(r => !r.duplicate)
      const res = await importApi.confirm({ portfolio_id: portfolioId, rows: toImport })
      setResult(res.data)
      setStep('done')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore durante l\'importazione')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    setFile(null); setPreview(null); setRows([]); setStep('upload')
    setError(''); setResult(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const visibleRows = includeDuplicates ? rows : rows.filter(r => !r.is_dividend || true)
  const tradeRows = rows.filter(r => !r.is_dividend)
  const divRows = rows.filter(r => r.is_dividend)

  return (
    <div className="space-y-6 max-w-5xl">
      <h1 className="text-2xl font-bold text-gray-100">Importa Transazioni</h1>

      {step === 'done' ? (
        <div className="card text-center py-12">
          <CheckCircle size={48} className="text-emerald-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-100 mb-2">Importazione completata!</h2>
          <p className="text-gray-400 mb-2">
            <span className="text-emerald-400 font-semibold">{result?.imported}</span> rig{result?.imported === 1 ? 'a' : 'he'} importat{result?.imported === 1 ? 'a' : 'e'}
          </p>
          {(result?.skipped ?? 0) > 0 && (
            <p className="text-gray-500 text-sm">{result!.skipped} saltate (duplicati)</p>
          )}
          {(result?.no_ticker ?? 0) > 0 && (
            <p className="flex items-center justify-center gap-1.5 text-amber-400 text-sm mt-1">
              <AlertCircle size={14} />
              {result!.no_ticker} saltate per ticker mancante
            </p>
          )}
          <button onClick={handleReset} className="btn-primary mt-6">Importa un altro file</button>
        </div>
      ) : (
        <div className="card space-y-5">
          {/* Step 1: Configure */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="label">Broker</label>
              <select className="input" value={broker} onChange={(e) => setBroker(e.target.value)} disabled={step === 'preview'}>
                {BROKERS.map((b) => <option key={b}>{b}</option>)}
              </select>
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label mb-0">Portafoglio</label>
                {step !== 'preview' && (
                  <button
                    type="button"
                    onClick={() => setShowNewPf(v => !v)}
                    className="text-xs text-gold-500 hover:text-gold-400 transition-colors flex items-center gap-1"
                  >
                    <Plus size={11} /> Nuovo
                  </button>
                )}
              </div>
              {showNewPf && step !== 'preview' && (
                <div className="bg-navy-700/60 border border-gray-600/40 rounded-lg p-3 mb-2 space-y-2">
                  <input className="input text-sm" placeholder="Nome portafoglio *" value={newPfName} onChange={e => setNewPfName(e.target.value)} />
                  <input className="input text-sm" placeholder="Broker (es. Fineco, DEGIRO…)" value={newPfBroker} onChange={e => setNewPfBroker(e.target.value)} />
                  <button type="button" onClick={handleCreatePortfolio} disabled={creatingPf || !newPfName.trim()} className="btn-primary text-sm py-1.5 w-full">
                    {creatingPf ? 'Creazione…' : 'Crea Portafoglio'}
                  </button>
                </div>
              )}
              <select className="input" value={portfolioId ?? ''} onChange={(e) => setPortfolioId(Number(e.target.value) || null)} disabled={step === 'preview'}>
                <option value="">— seleziona —</option>
                {portfolios.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}{p.broker ? ` — ${p.broker}` : ''}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">File CSV</label>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleFileChange}
                disabled={step === 'preview'}
                className="input text-sm file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-medium file:bg-gold-500/20 file:text-gold-500 cursor-pointer"
              />
            </div>
          </div>

          {step === 'upload' && EXPORT_HELP[broker] && (
            <div className="flex items-start gap-2 bg-navy-700/40 border border-gray-600/40 rounded-lg px-3 py-2.5">
              <Info size={15} className="text-gold-500/80 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-gray-400 leading-relaxed">
                <p className="text-gray-300 font-medium mb-1">Dove trovare i file da esportare ({broker})</p>
                <p className="mb-1">Puoi importare {EXPORT_HELP[broker].length === 2 ? 'due tipi di file' : 'questi file'}:</p>
                <ul className="space-y-1">
                  {EXPORT_HELP[broker].map((m, i) => (
                    <li key={i}>
                      <span className="text-gold-400/90 font-medium">{i + 1}) {m.title}</span> — {m.steps}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {step === 'upload' && (
            <div
              className="border-2 border-dashed border-gray-600/60 rounded-xl p-10 text-center cursor-pointer hover:border-gold-500/40 transition-colors"
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={36} className="text-gray-500 mx-auto mb-3" />
              <p className="text-gray-400 text-sm">{file ? file.name : 'Trascina il file qui o clicca per selezionare'}</p>
              {file && <p className="text-xs text-gold-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>}
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
              <AlertCircle size={16} />
              {error}
            </div>
          )}

          {step === 'upload' && (
            <div className="flex items-center gap-4">
              <button onClick={handlePreview} disabled={loading || !file || !portfolioId} className="btn-primary">
                {loading ? 'Analisi in corso…' : 'Analizza File'}
              </button>
              {file && !portfolioId && (
                <p className="text-amber-400 text-sm flex items-center gap-1.5">
                  <AlertCircle size={14} /> Seleziona o crea un portafoglio per procedere
                </p>
              )}
            </div>
          )}

          {/* Step 2: Preview */}
          {step === 'preview' && preview && (
            <div className="space-y-4">
              {/* Summary badges */}
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="flex items-center gap-2 text-gray-300">
                  <FileText size={16} className="text-gold-500" />
                  <strong className="text-gray-100">{preview.total}</strong> righe trovate
                </span>
                {tradeRows.length > 0 && (
                  <span className="badge-green">{tradeRows.length} operazioni</span>
                )}
                {divRows.length > 0 && (
                  <span className="badge bg-purple-900/40 text-purple-300 border border-purple-700/30">
                    {divRows.length} dividendi
                  </span>
                )}
                {preview.duplicates > 0 && (
                  <span className="text-amber-400">⚠️ {preview.duplicates} duplicati</span>
                )}
              </div>

              {/* Ticker note */}
              {(() => {
                const missingTicker = rows.filter(r => !r.ticker)
                if (!missingTicker.length) return null
                const tradesMissing = missingTicker.filter(r => !r.is_dividend).length
                const divsMissing   = missingTicker.filter(r => r.is_dividend).length
                return (
                  <div className="flex items-start gap-2 text-amber-400 text-xs bg-amber-900/20 border border-amber-700/30 rounded-lg px-3 py-2">
                    <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
                    <span>
                      <strong>{missingTicker.length} rig{missingTicker.length === 1 ? 'a' : 'he'} senza ticker</strong>
                      {tradesMissing > 0 && ` (${tradesMissing} operazion${tradesMissing === 1 ? 'e' : 'i'})`}
                      {divsMissing > 0 && ` (${divsMissing} dividend${divsMissing === 1 ? 'o' : 'i'})`}
                      {' '}— verranno <strong>saltate</strong> se non compili il ticker corretto.
                      Cerca il ticker nella colonna <strong>Ticker</strong> e selezionalo prima di confermare.
                    </span>
                  </div>
                )
              })()}

              {preview.duplicates > 0 && (
                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                  <input type="checkbox" checked={includeDuplicates} onChange={(e) => setIncludeDuplicates(e.target.checked)} className="w-4 h-4 accent-gold-500" />
                  Importa anche i duplicati
                </label>
              )}

              <div className="overflow-x-auto max-h-[480px] border border-gray-700/40 rounded-lg">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-navy-800 z-10">
                    <tr className="border-b border-gray-700/50">
                      {['', 'Data', 'Tipo', 'ISIN', 'Ticker', 'Nome', 'Qtà / Importo', 'Commissioni/Tasse', 'Valuta'].map((h) => (
                        <th key={h} className="text-left py-2 px-3 text-gray-400 font-medium uppercase whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => {
                      const dim = row.duplicate && !includeDuplicates
                      return (
                        <tr key={i} className={`border-b border-gray-700/20 ${dim ? 'opacity-40' : ''}`}>
                          <td className="py-2 pl-3 pr-1 whitespace-nowrap">
                            {row.duplicate
                              ? <span className="badge bg-amber-900/40 text-amber-400 border border-amber-700/30">DUP</span>
                              : <span className="badge-green">OK</span>
                            }
                          </td>
                          <td className="py-2 px-3 text-gray-300 whitespace-nowrap">{fmtDate(row.date)}</td>
                          <td className="py-2 px-3">{typeBadge(row)}</td>
                          <td className="py-2 px-3 text-gray-500 font-mono">{row.isin || '—'}</td>
                          <td className="py-2 px-2 min-w-[110px]">
                            <TickerSearchInput
                              value={row.ticker ?? ''}
                              onChange={val => handleTickerChange(i, val)}
                              placeholder="ticker…"
                              inputClassName="bg-navy-700 border border-gray-600/50 rounded px-2 py-1 pr-6 text-xs text-gray-100 font-mono uppercase w-full focus:outline-none focus:border-gold-500/60 placeholder-gray-600"
                            />
                          </td>
                          <td className="py-2 px-3 text-gray-300 max-w-[150px] truncate">{row.name || '—'}</td>
                          <td className="py-2 px-3 tabular-nums text-gray-300 whitespace-nowrap">
                            {row.is_dividend
                              ? <span className="text-purple-300">{fmtNum(row.price, 2)} {row.currency}</span>
                              : <span>{fmtNum(row.quantity, 6)} × {fmtNum(row.price, 4)}</span>
                            }
                          </td>
                          <td className="py-2 px-3 tabular-nums text-gray-500">
                            {row.fees > 0 ? fmtNum(row.fees, 2) : <span className="text-gray-700">—</span>}
                          </td>
                          <td className="py-2 px-3 text-gray-500">{row.currency}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {(() => {
                const toImport  = includeDuplicates ? rows : rows.filter(r => !r.duplicate)
                const willSkip  = toImport.filter(r => !r.ticker).length
                return (
                  <div className="flex flex-wrap items-center gap-3">
                    <button onClick={handleImport} disabled={loading} className="btn-primary">
                      {loading
                        ? 'Importazione…'
                        : `Conferma Importazione (${toImport.length} righe)`}
                    </button>
                    <button onClick={handleReset} className="btn-secondary">Annulla</button>
                    {willSkip > 0 && (
                      <span className="flex items-center gap-1.5 text-xs text-amber-400">
                        <AlertCircle size={13} />
                        {willSkip} rig{willSkip === 1 ? 'a' : 'he'} senza ticker verr{willSkip === 1 ? 'à' : 'anno'} saltata{willSkip === 1 ? '' : 'e'}
                      </span>
                    )}
                  </div>
                )
              })()}
            </div>
          )}
        </div>
      )}

      {/* Format guide */}
      <div className="card border-gray-700/30">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">Formati supportati</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs text-gray-400">
          <div>
            <div className="font-medium text-gray-300 mb-1">Fineco</div>
            <p>CSV con colonne: Data Ordine, Tipo Ordine (A/V), Titolo, ISIN, Quantità, Prezzo, Divisa, Commissioni</p>
          </div>
          <div>
            <div className="font-medium text-gray-300 mb-1">Directa SIM</div>
            <p>CSV con colonne: Data, Descrizione (con ISIN tra parentesi), Quantità, Prezzo, Commissioni, Valuta</p>
          </div>
          <div>
            <div className="font-medium text-gray-300 mb-1">Trade Republic</div>
            <p>
              Export CSV dalla app TR. Importa: acquisti, vendite, dividendi e Saveback.
              Il Saveback viene classificato come BUY (acquisto quote ETF), non come dividendo.
              Il backend suggerisce il ticker da ISIN; puoi correggerlo nella preview prima di confermare.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
