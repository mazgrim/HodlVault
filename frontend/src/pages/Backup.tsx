import { useState, useRef } from 'react'
import { Download, Upload, FileJson, FileSpreadsheet, CheckCircle, AlertCircle, Database } from 'lucide-react'
import { backupApi } from '../api'
import { useAuth } from '../hooks/useAuth'

interface ImportResult {
  portfolios_created: number
  instruments_created: number
  transactions_imported: number
  transactions_skipped: number
  dividends_imported: number
  dividends_skipped: number
  errors: string[]
}

// Estrae il filename dall'header Content-Disposition, con fallback.
function filenameFrom(resp: any, fallback: string): string {
  const cd: string = resp.headers?.['content-disposition'] || ''
  const m = cd.match(/filename="?([^";]+)"?/)
  return m ? m[1] : fallback
}

function triggerDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

export default function Backup() {
  const { isDemo } = useAuth()
  const [downloading, setDownloading] = useState<string | null>(null)
  const [error, setError] = useState('')

  // Import state
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const doExport = async (kind: 'json' | 'xlsx' | 'csv') => {
    setError('')
    setDownloading(kind)
    try {
      const call = kind === 'json' ? backupApi.exportJson
        : kind === 'xlsx' ? backupApi.exportXlsx
        : backupApi.exportCsv
      const fallback = kind === 'json' ? 'hodlvault_backup.json'
        : kind === 'xlsx' ? 'hodlvault_export.xlsx'
        : 'hodlvault_export_csv.zip'
      const res = await call()
      triggerDownload(res.data, filenameFrom(res, fallback))
    } catch {
      setError('Errore durante l\'esportazione. Riprova.')
    } finally {
      setDownloading(null)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    setFile(f || null)
    setPreview(null)
    setResult(null)
    setError('')
  }

  const handlePreview = async () => {
    if (!file) return
    setLoading(true); setError(''); setResult(null)
    try {
      const res = await backupApi.importPreview(file)
      setPreview(res.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'File di backup non valido')
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    if (!file) return
    setLoading(true); setError('')
    try {
      const res = await backupApi.importConfirm(file)
      setResult(res.data)
      setPreview(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore durante il ripristino')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    setFile(null); setPreview(null); setResult(null); setError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  const summaryLine = (r: ImportResult) => (
    <ul className="text-sm text-gray-300 space-y-1">
      {r.portfolios_created > 0 && <li>• <strong className="text-gray-100">{r.portfolios_created}</strong> portafogli creati</li>}
      {r.instruments_created > 0 && <li>• <strong className="text-gray-100">{r.instruments_created}</strong> strumenti aggiunti</li>}
      <li>• <strong className="text-emerald-400">{r.transactions_imported}</strong> transazioni {result ? 'importate' : 'da importare'}
        {r.transactions_skipped > 0 && <span className="text-gray-500"> ({r.transactions_skipped} già presenti)</span>}
      </li>
      <li>• <strong className="text-purple-300">{r.dividends_imported}</strong> dividendi {result ? 'importati' : 'da importare'}
        {r.dividends_skipped > 0 && <span className="text-gray-500"> ({r.dividends_skipped} già presenti)</span>}
      </li>
      {r.errors?.length > 0 && (
        <li className="text-amber-400">⚠️ {r.errors.length} avvisi: {r.errors.slice(0, 3).join('; ')}</li>
      )}
    </ul>
  )

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Backup e Ripristino</h1>
        <p className="text-gray-400 text-sm mt-1">
          Salva una copia locale dei tuoi dati o ripristinala su un'altra installazione.
          Il backup contiene solo i <strong>tuoi</strong> portafogli, transazioni e dividendi.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Export */}
      <div className="card space-y-4">
        <div className="flex items-center gap-2">
          <Download size={18} className="text-gold-500" />
          <h2 className="text-lg font-semibold text-gray-100">Esporta</h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="border border-gray-700/40 rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-2 text-gray-200 font-medium">
              <Database size={16} className="text-gold-400" /> Backup completo (JSON)
            </div>
            <p className="text-xs text-gray-400 leading-relaxed">
              Formato per il ripristino e il trasferimento tra le versioni desktop.
              Include tutti i dati necessari a ricostruire i portafogli.
            </p>
            <button onClick={() => doExport('json')} disabled={downloading !== null} className="btn-primary w-full">
              {downloading === 'json' ? 'Esportazione…' : 'Scarica backup JSON'}
            </button>
          </div>

          <div className="border border-gray-700/40 rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-2 text-gray-200 font-medium">
              <FileSpreadsheet size={16} className="text-emerald-400" /> Lista leggibile
            </div>
            <p className="text-xs text-gray-400 leading-relaxed">
              Transazioni e dividendi in chiaro (con valori anche in EUR),
              per consultarli o modificarli fuori dall'app.
            </p>
            <div className="flex gap-2">
              <button onClick={() => doExport('xlsx')} disabled={downloading !== null} className="btn-secondary flex-1 flex items-center justify-center gap-1.5">
                <FileSpreadsheet size={14} /> {downloading === 'xlsx' ? '…' : 'Excel'}
              </button>
              <button onClick={() => doExport('csv')} disabled={downloading !== null} className="btn-secondary flex-1 flex items-center justify-center gap-1.5">
                <FileJson size={14} /> {downloading === 'csv' ? '…' : 'CSV (zip)'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Import */}
      <div className="card space-y-4">
        <div className="flex items-center gap-2">
          <Upload size={18} className="text-gold-500" />
          <h2 className="text-lg font-semibold text-gray-100">Ripristina da backup JSON</h2>
        </div>

        {isDemo ? (
          <p className="text-sm text-amber-400 flex items-center gap-2">
            <AlertCircle size={15} /> Il ripristino non è disponibile in modalità demo.
          </p>
        ) : result ? (
          <div className="text-center py-6 space-y-3">
            <CheckCircle size={40} className="text-emerald-400 mx-auto" />
            <h3 className="text-lg font-bold text-gray-100">Ripristino completato</h3>
            <div className="inline-block text-left">{summaryLine(result)}</div>
            <div><button onClick={handleReset} className="btn-primary mt-2">Ripristina un altro file</button></div>
          </div>
        ) : (
          <>
            <p className="text-xs text-gray-400 leading-relaxed">
              L'import è <strong>additivo</strong>: aggiunge solo ciò che manca e salta i duplicati,
              senza cancellare i dati già presenti.
            </p>
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              onChange={handleFileChange}
              className="input text-sm file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-medium file:bg-gold-500/20 file:text-gold-500 cursor-pointer"
            />

            {preview && (
              <div className="bg-navy-700/40 border border-gray-600/40 rounded-lg px-4 py-3 space-y-2">
                <p className="text-sm text-gray-200 font-medium">Anteprima del ripristino</p>
                {summaryLine(preview)}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              {!preview ? (
                <button onClick={handlePreview} disabled={!file || loading} className="btn-primary">
                  {loading ? 'Analisi…' : 'Analizza backup'}
                </button>
              ) : (
                <>
                  <button onClick={handleImport} disabled={loading} className="btn-primary">
                    {loading ? 'Ripristino…' : 'Conferma ripristino'}
                  </button>
                  <button onClick={handleReset} className="btn-secondary">Annulla</button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
