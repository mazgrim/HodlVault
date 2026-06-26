import { useState } from 'react'
import { X } from 'lucide-react'
import { authApi } from '../api'
import PasswordField from './PasswordField'
import { generatePassword } from '../utils/password'

interface Props {
  onClose: () => void
}

export default function ChangePasswordModal({ onClose }: Props) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (newPassword.length < 8) { setError('La nuova password deve avere almeno 8 caratteri.'); return }
    if (newPassword !== confirm) { setError('Le due password non coincidono.'); return }
    setLoading(true)
    try {
      await authApi.changePassword(oldPassword, newPassword)
      setDone(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore durante il cambio password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[70] bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card border-gray-700/60 w-full max-w-sm relative" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} className="absolute top-3 right-3 text-gray-500 hover:text-gray-300">
          <X size={18} />
        </button>
        <h2 className="text-base font-semibold text-gray-200 mb-4">Cambia password</h2>

        {done ? (
          <div className="space-y-4">
            <div className="text-emerald-400 text-sm bg-emerald-900/20 border border-emerald-700/30 rounded-lg px-3 py-2">
              Password aggiornata con successo.
            </div>
            <button onClick={onClose} className="btn-primary w-full">Chiudi</button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="label">Password attuale</label>
              <PasswordField value={oldPassword} onChange={setOldPassword} required autoFocus />
            </div>
            <div>
              <label className="label">Nuova password</label>
              <PasswordField
                value={newPassword}
                onChange={setNewPassword}
                required
                onGenerate={() => { const p = generatePassword(); setNewPassword(p); setConfirm(p) }}
              />
              <p className="text-xs text-gray-600 mt-1">Almeno 8 caratteri.</p>
            </div>
            <div>
              <label className="label">Conferma nuova password</label>
              <PasswordField value={confirm} onChange={setConfirm} required />
            </div>

            {error && (
              <div className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full">
              {loading ? 'Salvataggio...' : 'Cambia password'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
