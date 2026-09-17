import { useState } from 'react'
import { X } from 'lucide-react'
import { marketApi } from '../api'
import PriceSourceConfig, { type PriceSourceValue } from './PriceSourceConfig'

// ── Types ─────────────────────────────────────────────────────────────────────

interface InstrumentData {
  id: number
  ticker: string
  isin: string | null
  name: string
  asset_class: string
  currency: string
  price_source: string
  custom_url: string | null
  custom_jsonpath_price: string | null
  custom_jsonpath_date: string | null
}

interface Props {
  instrument: InstrumentData
  onClose: () => void
  onSaved: () => void
}

const ASSET_CLASSES = ['EQUITY', 'ETF', 'BOND', 'CRYPTO', 'COMMODITY', 'REAL_ESTATE', 'CASH', 'OTHER']

// ── Component ─────────────────────────────────────────────────────────────────

/** Modifica anagrafica e fonte prezzo di uno strumento esistente. */
export default function InstrumentSettingsModal({ instrument, onClose, onSaved }: Props) {
  const [name, setName]             = useState(instrument.name)
  const [ticker, setTicker]         = useState(instrument.ticker)
  const [assetClass, setAssetClass] = useState(instrument.asset_class)
  const [currency, setCurrency]     = useState(instrument.currency)
  const [source, setSource]         = useState<PriceSourceValue>({
    price_source:          instrument.price_source || 'YAHOO',
    custom_url:            instrument.custom_url || '',
    custom_jsonpath_price: instrument.custom_jsonpath_price || '',
    custom_jsonpath_date:  instrument.custom_jsonpath_date || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (source.price_source === 'CUSTOM_JSON' && (!source.custom_url || !source.custom_jsonpath_price)) {
      setError('Per la fonte JSON servono URL e JSONPath del prezzo.')
      return
    }
    if (!ticker.trim()) {
      setError('Il ticker è obbligatorio.')
      return
    }
    setSaving(true); setError('')
    try {
      await marketApi.updateInstrument(instrument.id, {
        name: name.trim(),
        ticker: ticker.trim().toUpperCase(),
        asset_class: assetClass,
        currency: currency.trim().toUpperCase() || 'EUR',
        price_source: source.price_source,
        custom_url: source.custom_url.trim() || null,
        custom_jsonpath_price: source.custom_jsonpath_price.trim() || null,
        custom_jsonpath_date: source.custom_jsonpath_date.trim() || null,
      })
      onSaved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore nel salvataggio')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-navy-800 border border-gray-700/50 rounded-xl w-full max-w-lg max-h-[92vh] overflow-y-auto shadow-2xl">

        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/40">
          <h2 className="text-lg font-semibold text-gray-100">
            Impostazioni Strumento
            <span className="text-sm text-gray-500 font-normal font-mono ml-2">{instrument.ticker}</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200 transition-colors">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="label">Nome</label>
            <input className="input" value={name} onChange={e => setName(e.target.value)} required />
          </div>

          <div>
            <label className="label">Ticker</label>
            <input
              className="input uppercase font-mono"
              value={ticker}
              onChange={e => setTicker(e.target.value)}
              required
            />
            {ticker.trim().toUpperCase() !== instrument.ticker && (
              <p className="text-[11px] text-amber-400/90 mt-1">
                Cambiando il ticker cambia il simbolo Yahoo da cui arrivano i prezzi. Dopo il salvataggio ricarica lo storico
                ("Carica storico" nella sidebar): i prezzi già scaricati restano quelli del vecchio ticker.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Classe</label>
              <select className="input" value={assetClass} onChange={e => setAssetClass(e.target.value)}>
                {ASSET_CLASSES.map(ac => <option key={ac} value={ac}>{ac.replace('_', ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Valuta</label>
              <input className="input uppercase" value={currency} onChange={e => setCurrency(e.target.value)} />
            </div>
          </div>

          <PriceSourceConfig
            value={source}
            onChange={patch => setSource(s => ({ ...s, ...patch }))}
            isin={instrument.isin}
            ticker={instrument.ticker}
          />

          {error && (
            <p className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Annulla</button>
            <button type="submit" disabled={saving} className="btn-primary flex-1">
              {saving ? 'Salvataggio…' : 'Salva'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
