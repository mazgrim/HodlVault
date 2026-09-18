import { useState, useEffect, useCallback } from 'react'
import { Split, Plus, Trash2, Loader2 } from 'lucide-react'
import { splitApi } from '../api'
import { fmtDate } from '../utils/format'

interface SplitRow {
  id: number
  date: string
  old_shares: number
  new_shares: number
  note: string | null
}

interface Props {
  instrumentId: number
  onChanged: () => void          // ricarica il dettaglio (posizione/P&L cambiano)
}

/** Split / raggruppamenti azionari dello strumento. Un raggruppamento 10:1 (10
 *  vecchie → 1 nuova) chiude correttamente una posizione poi rivenduta: l'app
 *  normalizza le transazioni precedenti (quantità e prezzo) alla data dello split. */
export default function SplitSection({ instrumentId, onChanged }: Props) {
  const [rows, setRows] = useState<SplitRow[]>([])
  const [showForm, setShowForm] = useState(false)
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [oldShares, setOldShares] = useState('10')
  const [newShares, setNewShares] = useState('1')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await splitApi.list(instrumentId)
      setRows(res.data)
    } catch {
      setRows([])
    }
  }, [instrumentId])

  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    const oldN = parseFloat(oldShares.replace(',', '.'))
    const newN = parseFloat(newShares.replace(',', '.'))
    if (!oldN || !newN || oldN <= 0 || newN <= 0) {
      setError('Inserisci un rapporto valido (es. 10 → 1).')
      return
    }
    setSaving(true); setError('')
    try {
      await splitApi.create({ instrument_id: instrumentId, date, old_shares: oldN, new_shares: newN, note: note.trim() || undefined })
      setShowForm(false); setNote('')
      await load()
      onChanged()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore nel salvataggio dello split.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    await splitApi.delete(id)
    await load()
    onChanged()
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between gap-3 mb-1">
        <div className="flex items-center gap-2">
          <Split size={16} className="text-gold-500" />
          <h2 className="text-base font-semibold text-gray-200">Split / Raggruppamenti</h2>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border border-gold-500/50 bg-gold-500/15 text-gold-300 hover:bg-gold-500/25 transition-colors"
        >
          <Plus size={14} /> Aggiungi split
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Raggruppamento (es. 10 → 1) o frazionamento (es. 1 → 3). Le transazioni prima della data
        vengono riadattate (quantità e prezzo), così la posizione si chiude e il P&L resta corretto.
      </p>

      {showForm && (
        <div className="bg-navy-700/60 border border-gray-600/40 rounded-lg p-3 mb-3 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <label className="label">Data</label>
              <input type="date" value={date} onChange={e => setDate(e.target.value)} className="input text-sm" />
            </div>
            <div>
              <label className="label">Vecchie</label>
              <input type="number" min="0" step="any" value={oldShares} onChange={e => setOldShares(e.target.value)} className="input text-sm" placeholder="10" />
            </div>
            <div>
              <label className="label">Nuove</label>
              <input type="number" min="0" step="any" value={newShares} onChange={e => setNewShares(e.target.value)} className="input text-sm" placeholder="1" />
            </div>
            <div>
              <label className="label">Nota (opz.)</label>
              <input type="text" value={note} onChange={e => setNote(e.target.value)} className="input text-sm" placeholder="raggruppamento" />
            </div>
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex items-center gap-2">
            <button onClick={handleAdd} disabled={saving} className="btn-primary text-sm py-1.5">
              {saving ? <Loader2 size={14} className="animate-spin" /> : 'Salva split'}
            </button>
            <button onClick={() => { setShowForm(false); setError('') }} className="btn-secondary text-sm py-1.5">Annulla</button>
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="text-gray-500 text-sm">Nessuno split registrato.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.map(s => (
            <div key={s.id} className="flex items-center justify-between gap-3 bg-navy-700/40 border border-gray-600/30 rounded-lg px-3 py-2 text-sm">
              <div className="flex items-center gap-3">
                <span className="text-gray-300 tabular-nums">{fmtDate(s.date)}</span>
                <span className="font-mono text-gold-300">{s.old_shares} → {s.new_shares}</span>
                {s.note && <span className="text-gray-500 text-xs">{s.note}</span>}
              </div>
              <button
                onClick={() => handleDelete(s.id)}
                title="Elimina split"
                className="text-gray-500 hover:text-red-400 transition-colors"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
