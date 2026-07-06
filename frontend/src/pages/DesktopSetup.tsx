import { useState } from 'react'
import { useAuth } from '../hooks/useAuth'

export default function DesktopSetup() {
  const { desktopSetup } = useAuth()
  const [username, setUsername] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = username.trim()
    if (!name) return
    setError('')
    setLoading(true)
    try {
      await desktopSetup(name)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore durante la configurazione. Riprova.')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-navy-900 flex items-center justify-center p-4">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-gold-500/5 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-gold-500/5 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-sm relative z-10">
        <div className="flex flex-col items-center mb-8">
          <img src="/hodlvault_logo.svg" alt="HodlVault" className="w-28 h-28 object-contain" />
          <div className="mt-3 text-center">
            <div className="text-gold-400 font-bold tracking-[0.3em] text-2xl" style={{ fontFamily: 'Georgia, serif' }}>HODL VAULT</div>
            <div className="text-gold-600 tracking-[0.2em] text-xs mt-1" style={{ fontFamily: 'Georgia, serif' }}>Portfolio Tracker</div>
          </div>
        </div>

        <div className="card border-gray-700/60">
          <h1 className="text-lg font-bold text-gray-100 mb-1">Benvenuto</h1>
          <p className="text-sm text-gray-400 mb-5">
            Scegli un nome utente per il tuo profilo locale. Puoi usare il tuo nome:
            i dati restano solo su questo computer.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">Nome utente</label>
              <input
                className="input"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="es. Alessandro"
                maxLength={64}
                autoFocus
                required
              />
            </div>

            {error && (
              <div className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <button type="submit" disabled={loading || !username.trim()} className="btn-primary w-full mt-2">
              {loading ? 'Creazione…' : 'Inizia'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-600 mt-6">HodlVault — Self-hosted portfolio tracker</p>
      </div>
    </div>
  )
}
