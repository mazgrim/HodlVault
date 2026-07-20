import { useState } from 'react'
import { Loader2, PlugZap, CheckCircle2, XCircle } from 'lucide-react'
import { marketApi } from '../api'
import { fmtDate, fmtNum } from '../utils/format'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PriceSourceValue {
  price_source: string            // 'YAHOO' | 'MANUAL' | 'CUSTOM_JSON'
  custom_url: string
  custom_jsonpath_price: string
  custom_jsonpath_date: string
}

interface Props {
  value: PriceSourceValue
  onChange: (patch: Partial<PriceSourceValue>) => void
  /** ISIN/ticker dello strumento: servono per risolvere i placeholder nel test */
  isin?: string | null
  ticker?: string | null
}

const SOURCES = [
  { key: 'YAHOO',       label: 'Yahoo Finance',  desc: 'Automatico dal ticker (default)' },
  { key: 'MANUAL',      label: 'Manuale',        desc: 'Prezzi inseriti a mano' },
  { key: 'CUSTOM_JSON', label: 'Endpoint JSON',  desc: 'Fetch da URL configurabile' },
] as const

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * Selettore della fonte prezzo di uno strumento, con i campi condizionali per
 * la fonte JSON custom e il pulsante "Testa configurazione" (chiamata di prova
 * che mostra il valore estratto prima di salvare).
 */
export default function PriceSourceConfig({ value, onChange, isin, ticker }: Props) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ price: number; price_date: string; resolved_url: string } | null>(null)
  const [testError, setTestError] = useState('')

  const isCustom = value.price_source === 'CUSTOM_JSON'

  const handleTest = async () => {
    setTesting(true); setTestResult(null); setTestError('')
    try {
      const res = await marketApi.testCustomSource({
        url: value.custom_url,
        jsonpath_price: value.custom_jsonpath_price,
        jsonpath_date: value.custom_jsonpath_date || null,
        isin, ticker,
      })
      setTestResult(res.data)
    } catch (err: any) {
      setTestError(err.response?.data?.detail || 'Test fallito')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="label">Fonte prezzo</label>
        <div className="grid grid-cols-3 gap-2">
          {SOURCES.map(s => (
            <button
              key={s.key}
              type="button"
              onClick={() => onChange({ price_source: s.key })}
              className={`rounded-lg border px-2 py-2 text-left transition-colors ${
                value.price_source === s.key
                  ? 'bg-gold-500/15 border-gold-500/40 text-gold-400'
                  : 'bg-navy-700 border-gray-600/40 text-gray-400 hover:text-gray-200'
              }`}
            >
              <span className="block text-xs font-semibold">{s.label}</span>
              <span className="block text-[10px] leading-tight opacity-75 mt-0.5">{s.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {isCustom && (
        <div className="bg-navy-700/50 border border-gray-600/40 rounded-lg p-3 space-y-3">
          <div>
            <label className="label">URL endpoint JSON</label>
            <input
              className="input font-mono text-xs"
              placeholder="https://api.example.com/quote/{ISIN}"
              value={value.custom_url}
              onChange={e => onChange({ custom_url: e.target.value })}
            />
            <p className="text-[11px] text-gray-500 mt-1">
              I placeholder <code className="text-gray-400">{'{ISIN}'}</code> e{' '}
              <code className="text-gray-400">{'{TICKER}'}</code> vengono sostituiti coi dati dello strumento.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">JSONPath prezzo</label>
              <input
                className="input font-mono text-xs"
                placeholder="$.quote.price"
                value={value.custom_jsonpath_price}
                onChange={e => onChange({ custom_jsonpath_price: e.target.value })}
              />
            </div>
            <div>
              <label className="label">JSONPath data (opz.)</label>
              <input
                className="input font-mono text-xs"
                placeholder="$.quote.date"
                value={value.custom_jsonpath_date}
                onChange={e => onChange({ custom_jsonpath_date: e.target.value })}
              />
            </div>
          </div>
          <p className="text-[11px] text-gray-500 -mt-1">
            Senza JSONPath della data viene usata la data corrente.
          </p>

          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !value.custom_url || !value.custom_jsonpath_price}
            className="btn-secondary text-sm py-1.5 w-full flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {testing ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
            {testing ? 'Test in corso…' : 'Testa configurazione'}
          </button>

          {testResult && (
            <div className="flex items-start gap-2 text-xs bg-emerald-900/20 border border-emerald-700/30 rounded-lg px-3 py-2">
              <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0 mt-0.5" />
              <div className="text-emerald-300">
                <p>
                  Prezzo estratto: <span className="font-semibold tabular-nums">{fmtNum(testResult.price, 4)}</span>
                  {' '}— data quotazione: {fmtDate(testResult.price_date)}
                </p>
                <p className="text-emerald-400/60 break-all mt-0.5">{testResult.resolved_url}</p>
              </div>
            </div>
          )}
          {testError && (
            <div className="flex items-start gap-2 text-xs bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
              <XCircle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-red-300">{testError}</p>
            </div>
          )}
        </div>
      )}

      {value.price_source === 'MANUAL' && (
        <p className="text-[11px] text-gray-500">
          I prezzi si inseriscono dalla pagina dello strumento (prezzo corrente e quotazioni storiche).
          Un avviso segnala quando l'ultimo prezzo ha più di 7 giorni.
        </p>
      )}
    </div>
  )
}
