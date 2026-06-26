import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { authApi } from '../api'
import PasswordField from '../components/PasswordField'
import { generatePassword } from '../utils/password'

export default function Login() {
  const { login, loginDemo, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [loading, setLoading] = useState(false)

  const switchMode = (m: 'login' | 'register' | 'forgot') => {
    setMode(m); setError(''); setInfo('')
  }

  const handleDemo = async () => {
    setError('')
    setLoading(true)
    try {
      await loginDemo()
      navigate('/')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore avvio demo.')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setInfo('')
    setLoading(true)
    try {
      if (mode === 'forgot') {
        const res = await authApi.forgotPassword(username)
        setInfo(res.data?.detail || 'Richiesta inviata. Contatta l\'amministratore.')
        return
      }
      if (mode === 'login') {
        await login(username, password)
      } else {
        await register(username, email, password)
      }
      navigate('/')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Errore. Riprova.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-navy-900 flex items-center justify-center p-4">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-gold-500/5 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-gold-500/5 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-sm relative z-10">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <img src="/hodlvault_logo.svg" alt="HodlVault" className="w-28 h-28 object-contain" />
          <div className="mt-3 text-center">
            <div className="text-gold-400 font-bold tracking-[0.3em] text-2xl" style={{ fontFamily: 'Georgia, serif' }}>HODL VAULT</div>
            <div className="text-gold-600 tracking-[0.2em] text-xs mt-1" style={{ fontFamily: 'Georgia, serif' }}>Portfolio Tracker</div>
          </div>
        </div>

        {/* Card */}
        <div className="card border-gray-700/60">
          <div className="flex border-b border-gray-700/40 mb-6">
            <button
              className={`flex-1 pb-3 text-sm font-semibold transition-colors ${mode !== 'register' ? 'text-gold-500 border-b-2 border-gold-500' : 'text-gray-500 hover:text-gray-300'}`}
              onClick={() => switchMode('login')}
            >
              Accedi
            </button>
            <button
              className={`flex-1 pb-3 text-sm font-semibold transition-colors ${mode === 'register' ? 'text-gold-500 border-b-2 border-gold-500' : 'text-gray-500 hover:text-gray-300'}`}
              onClick={() => switchMode('register')}
            >
              Registrati
            </button>
          </div>

          {mode === 'forgot' && (
            <p className="text-xs text-gray-400 mb-4">
              Inserisci il tuo username o la tua email. La richiesta di reset verrà segnalata all'amministratore, che ti fornirà una nuova password.
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">{mode === 'register' ? 'Username' : 'Username o email'}</label>
              <input className="input" type="text" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </div>
            {mode === 'register' && (
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
            )}
            {mode !== 'forgot' && (
              <div>
                <div className="flex items-center justify-between">
                  <label className="label">Password</label>
                  {mode === 'login' && (
                    <button type="button" onClick={() => switchMode('forgot')}
                      className="text-xs text-gold-500/80 hover:text-gold-400 mb-1">
                      Password dimenticata?
                    </button>
                  )}
                </div>
                <PasswordField
                  value={password}
                  onChange={setPassword}
                  required
                  onGenerate={mode === 'register' ? () => setPassword(generatePassword()) : undefined}
                />
              </div>
            )}

            {error && (
              <div className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                {error}
              </div>
            )}
            {info && (
              <div className="text-emerald-400 text-sm bg-emerald-900/20 border border-emerald-700/30 rounded-lg px-3 py-2">
                {info}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full mt-2">
              {loading ? 'Caricamento...' : mode === 'login' ? 'Accedi' : mode === 'register' ? 'Registrati' : 'Invia richiesta'}
            </button>

            {mode === 'forgot' && (
              <button type="button" onClick={() => switchMode('login')}
                className="w-full text-center text-xs text-gray-400 hover:text-gray-200">
                ← Torna al login
              </button>
            )}
          </form>
        </div>

        {/* Demo CTA */}
        <div className="mt-5 text-center">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-px bg-gray-700/50" />
            <span className="text-xs text-gray-600">oppure</span>
            <div className="flex-1 h-px bg-gray-700/50" />
          </div>
          <button
            onClick={handleDemo}
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-lg border border-gold-500/30 bg-gold-500/5 hover:bg-gold-500/10 text-gold-400 hover:text-gold-300 text-sm font-medium transition-all duration-150 flex items-center justify-center gap-2"
          >
            <span className="text-base">🚀</span>
            {loading ? 'Avvio demo...' : 'Prova la Demo — nessun account richiesto'}
          </button>
          <p className="text-xs text-gray-600 mt-2">Portafoglio pre-popolato in sola lettura</p>
        </div>

        <p className="text-center text-xs text-gray-600 mt-6">HodlVault — Self-hosted portfolio tracker</p>
      </div>
    </div>
  )
}
