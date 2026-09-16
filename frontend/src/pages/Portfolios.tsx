import { useState } from 'react'
import { Wallet, Pencil, Trash2, Check, X, Plus, AlertTriangle } from 'lucide-react'
import { usePortfolios, Portfolio } from '../context/PortfoliosContext'
import { portfolioApi, txApi, divApi } from '../api'
import { fmtDate } from '../utils/format'

export default function Portfolios() {
  const { portfolios, reload } = usePortfolios()

  // ── Rinomina inline ─────────────────────────────────────────────────────────
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editBroker, setEditBroker] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const startEdit = (p: Portfolio) => {
    setEditingId(p.id); setEditName(p.name); setEditBroker(p.broker ?? ''); setError('')
  }
  const cancelEdit = () => { setEditingId(null); setError('') }
  const saveEdit = async (id: number) => {
    if (!editName.trim()) return
    setSaving(true); setError('')
    try {
      await portfolioApi.update(id, { name: editName.trim(), broker: editBroker.trim() })
      reload(); setEditingId(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Errore nel salvataggio')
    } finally { setSaving(false) }
  }

  // ── Elimina (con conteggio di ciò che verrà cancellato) ─────────────────────
  const [delTarget, setDelTarget] = useState<Portfolio | null>(null)
  const [delCounts, setDelCounts] = useState<{ tx: number; div: number } | null>(null)
  const [deleting, setDeleting] = useState(false)

  const openDelete = async (p: Portfolio) => {
    setDelTarget(p); setDelCounts(null)
    try {
      const [tx, div] = await Promise.all([txApi.list(p.id), divApi.list(p.id)])
      setDelCounts({ tx: tx.data.length, div: div.data.length })
    } catch {
      setDelCounts({ tx: -1, div: -1 })  // conteggio non disponibile
    }
  }
  const confirmDelete = async () => {
    if (!delTarget) return
    setDeleting(true)
    try {
      await portfolioApi.delete(delTarget.id)
      reload(); setDelTarget(null); setDelCounts(null)
    } finally { setDeleting(false) }
  }

  // ── Crea ────────────────────────────────────────────────────────────────────
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newBroker, setNewBroker] = useState('')
  const [creating, setCreating] = useState(false)
  const createPf = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await portfolioApi.create({ name: newName.trim(), broker: newBroker.trim() || undefined })
      reload(); setShowNew(false); setNewName(''); setNewBroker('')
    } finally { setCreating(false) }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
          <Wallet size={22} className="text-gold-500" /> Portafogli
        </h1>
        <button onClick={() => setShowNew(v => !v)} className="btn-secondary text-sm flex items-center gap-2">
          <Plus size={15} /> Nuovo
        </button>
      </div>

      {showNew && (
        <div className="card space-y-3">
          <h2 className="text-sm font-semibold text-gray-200">Nuovo portafoglio</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input className="input text-sm" placeholder="Nome *" value={newName} onChange={e => setNewName(e.target.value)} autoFocus />
            <input className="input text-sm" placeholder="Broker (opzionale)" value={newBroker} onChange={e => setNewBroker(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <button onClick={createPf} disabled={creating || !newName.trim()} className="btn-primary text-sm disabled:opacity-50">
              {creating ? 'Creazione…' : 'Crea'}
            </button>
            <button onClick={() => setShowNew(false)} className="btn-secondary text-sm">Annulla</button>
          </div>
        </div>
      )}

      <div className="card divide-y divide-gray-700/30">
        {portfolios.length === 0 ? (
          <p className="text-gray-500 text-sm py-4">Nessun portafoglio. Creane uno con "Nuovo".</p>
        ) : portfolios.map(p => (
          <div key={p.id} className="py-3 first:pt-0 last:pb-0">
            {editingId === p.id ? (
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <input
                  className="input text-sm flex-1"
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  placeholder="Nome *"
                  autoFocus
                  onKeyDown={e => { if (e.key === 'Enter') saveEdit(p.id); if (e.key === 'Escape') cancelEdit() }}
                />
                <input
                  className="input text-sm flex-1"
                  value={editBroker}
                  onChange={e => setEditBroker(e.target.value)}
                  placeholder="Broker (opzionale)"
                  onKeyDown={e => { if (e.key === 'Enter') saveEdit(p.id); if (e.key === 'Escape') cancelEdit() }}
                />
                <div className="flex gap-1">
                  <button onClick={() => saveEdit(p.id)} disabled={saving || !editName.trim()} className="p-2 rounded-lg text-emerald-400 hover:bg-emerald-900/30 disabled:opacity-40" title="Salva">
                    <Check size={16} />
                  </button>
                  <button onClick={cancelEdit} className="p-2 rounded-lg text-gray-400 hover:bg-navy-700" title="Annulla">
                    <X size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium text-gray-100 truncate">{p.name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {p.broker ? `${p.broker} · ` : ''}{p.currency} · creato il {fmtDate(p.created_at)}
                  </div>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  <button onClick={() => startEdit(p)} className="p-2 rounded-lg text-gray-400 hover:text-gold-400 hover:bg-navy-700 transition-colors" title="Rinomina">
                    <Pencil size={16} />
                  </button>
                  <button onClick={() => openDelete(p)} className="p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-navy-700 transition-colors" title="Elimina">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {error && editingId !== null && (
          <p className="text-red-400 text-xs pt-2">{error}</p>
        )}
      </div>

      {/* ── Modale conferma eliminazione ─────────────────────────────────────── */}
      {delTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => !deleting && setDelTarget(null)}>
          <div className="card max-w-md w-full" onClick={e => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-3">
              <div className="p-2 rounded-lg bg-red-900/30 text-red-400 flex-shrink-0">
                <AlertTriangle size={18} />
              </div>
              <div>
                <h3 className="text-base font-semibold text-gray-100">Eliminare "{delTarget.name}"?</h3>
                <p className="text-sm text-gray-400 mt-1">
                  L'operazione è <strong className="text-red-400">irreversibile</strong> e rimuove il portafoglio con
                  {' '}<strong>tutte le sue transazioni e i dividendi</strong>.
                </p>
              </div>
            </div>

            <div className="bg-navy-700/50 border border-gray-700/40 rounded-lg px-3 py-2 text-sm text-gray-300 mb-4">
              {delCounts === null ? (
                <span className="text-gray-500">Conteggio in corso…</span>
              ) : delCounts.tx < 0 ? (
                <span className="text-amber-400">Impossibile contare gli elementi collegati, procedi con cautela.</span>
              ) : (
                <span>
                  Verranno eliminati: <strong className="text-gray-100">{delCounts.tx}</strong> transazion{delCounts.tx === 1 ? 'e' : 'i'}
                  {' '}e <strong className="text-gray-100">{delCounts.div}</strong> dividend{delCounts.div === 1 ? 'o' : 'i'}.
                </span>
              )}
            </div>

            <div className="flex justify-end gap-3">
              <button onClick={() => setDelTarget(null)} disabled={deleting} className="btn-secondary text-sm disabled:opacity-50">Annulla</button>
              <button
                onClick={confirmDelete}
                disabled={deleting || delCounts === null}
                className="text-sm flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/90 hover:bg-red-600 text-white font-semibold transition-colors disabled:opacity-50"
              >
                <Trash2 size={14} />
                {deleting ? 'Eliminazione…' : 'Elimina definitivamente'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
