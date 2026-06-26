import { useState, useEffect } from 'react'
import { adminApi } from '../api'
import { fmtDate, fmtDateTime } from '../utils/format'
import { useAuth } from '../hooks/useAuth'
import { Shield, UserCheck, UserX, Trash2, KeyRound, X, ShieldAlert, Unlock, ScrollText } from 'lucide-react'
import { PageSpinner } from '../components/Spinner'
import PasswordField from '../components/PasswordField'
import { generatePassword } from '../utils/password'

interface User { id: number; username: string; email: string; is_active: boolean; is_admin: boolean; created_at: string }
interface ResetReq { id: number; user_id: number; username: string; email: string; created_at: string }
interface LoginAttempt { id: number; identifier: string | null; ip_address: string | null; user_agent: string | null; success: boolean; blocked: boolean; created_at: string }
interface LockoutEntry { type: 'ip' | 'identifier'; value: string; fail_count: number }
interface SecurityStatus { max_attempts: number; lockout_minutes: number; locked: LockoutEntry[] }

export default function Admin() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [requests, setRequests] = useState<ResetReq[]>([])
  const [loading, setLoading] = useState(true)

  // Reset-password modal
  const [resetUser, setResetUser] = useState<{ id: number; username: string } | null>(null)
  const [newPw, setNewPw] = useState('')
  const [resetErr, setResetErr] = useState('')
  const [resetDone, setResetDone] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)

  // Access log / lockout
  const [attempts, setAttempts] = useState<LoginAttempt[]>([])
  const [security, setSecurity] = useState<SecurityStatus | null>(null)
  const [onlyFailed, setOnlyFailed] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [u, r] = await Promise.all([adminApi.users(), adminApi.passwordRequests()])
      setUsers(u.data)
      setRequests(r.data)
    } finally { setLoading(false) }
  }

  const loadSecurity = async (failedOnly = onlyFailed) => {
    const [a, s] = await Promise.all([
      adminApi.loginAttempts({ limit: 100, only_failed: failedOnly }),
      adminApi.securityStatus(),
    ])
    setAttempts(a.data)
    setSecurity(s.data)
  }

  useEffect(() => { load(); loadSecurity() }, [])

  const toggleOnlyFailed = async () => {
    const next = !onlyFailed
    setOnlyFailed(next)
    const a = await adminApi.loginAttempts({ limit: 100, only_failed: next })
    setAttempts(a.data)
  }

  const unlock = async (entry: LockoutEntry) => {
    await adminApi.clearLockout(entry.type === 'ip' ? { ip_address: entry.value } : { identifier: entry.value })
    loadSecurity()
  }

  const openReset = (id: number, username: string) => {
    setResetUser({ id, username }); setNewPw(''); setResetErr(''); setResetDone(false)
  }

  const submitReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setResetErr('')
    if (newPw.length < 8) { setResetErr('La password deve avere almeno 8 caratteri.'); return }
    if (!resetUser) return
    setResetLoading(true)
    try {
      await adminApi.resetPassword(resetUser.id, newPw)
      setResetDone(true)
      load()
    } catch (err: any) {
      setResetErr(err.response?.data?.detail || 'Errore durante il reset.')
    } finally {
      setResetLoading(false)
    }
  }

  if (!me?.is_admin) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-gray-500">Accesso riservato agli amministratori.</p>
    </div>
  )

  const toggle = async (id: number, field: 'is_active' | 'is_admin', current: boolean) => {
    await adminApi.updateUser(id, { [field]: !current })
    load()
  }

  const del = async (id: number) => {
    if (!confirm('Eliminare questo utente e tutti i suoi dati?')) return
    await adminApi.deleteUser(id)
    load()
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <Shield size={22} className="text-gold-500" />
        <h1 className="text-2xl font-bold text-gray-100">Amministrazione Utenti</h1>
      </div>

      {!loading && requests.length > 0 && (
        <div className="card border-red-500/30">
          <div className="flex items-center gap-2 mb-3">
            <KeyRound size={16} className="text-red-400" />
            <h2 className="text-sm font-semibold text-gray-200">
              Richieste di reset password ({requests.length})
            </h2>
          </div>
          <div className="space-y-2">
            {requests.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3 text-sm bg-navy-900/40 rounded-lg px-3 py-2">
                <div className="min-w-0">
                  <span className="font-medium text-gray-100">{r.username}</span>
                  <span className="text-gray-500"> · {r.email}</span>
                  <span className="text-gray-600 text-xs ml-2">{fmtDate(r.created_at)}</span>
                </div>
                <button
                  onClick={() => openReset(r.user_id, r.username)}
                  className="flex-shrink-0 px-3 py-1 rounded-lg bg-gold-500/15 text-gold-400 hover:bg-gold-500/25 text-xs font-medium transition-colors"
                >
                  Reset password
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading ? <PageSpinner /> : (
        <div className="card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  {['ID', 'Username', 'Email', 'Registrato', 'Stato', 'Admin', 'Azioni'].map((h) => (
                    <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="table-row-hover border-b border-gray-700/20">
                    <td className="py-3 pr-4 text-gray-500 text-xs">{u.id}</td>
                    <td className="py-3 pr-4 font-medium text-gray-100">
                      {u.username}
                      {u.id === me.id && <span className="ml-2 badge-gold">tu</span>}
                    </td>
                    <td className="py-3 pr-4 text-gray-400">{u.email}</td>
                    <td className="py-3 pr-4 text-gray-400">{fmtDate(u.created_at)}</td>
                    <td className="py-3 pr-4">
                      <span className={u.is_active ? 'badge-green' : 'badge-red'}>
                        {u.is_active ? 'Attivo' : 'Disabilitato'}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      {u.is_admin ? <span className="badge-gold">Admin</span> : <span className="text-gray-600 text-xs">—</span>}
                    </td>
                    <td className="py-3">
                      {u.id !== me.id && (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => toggle(u.id, 'is_active', u.is_active)}
                            title={u.is_active ? 'Disabilita' : 'Abilita'}
                            className="p-1.5 rounded hover:bg-navy-700 text-gray-400 hover:text-gray-200 transition-colors"
                          >
                            {u.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                          </button>
                          <button
                            onClick={() => toggle(u.id, 'is_admin', u.is_admin)}
                            title={u.is_admin ? 'Rimuovi admin' : 'Promuovi admin'}
                            className="p-1.5 rounded hover:bg-navy-700 text-gray-400 hover:text-gold-500 transition-colors"
                          >
                            <Shield size={15} />
                          </button>
                          <button
                            onClick={() => openReset(u.id, u.username)}
                            title="Reset password"
                            className="p-1.5 rounded hover:bg-navy-700 text-gray-400 hover:text-gold-500 transition-colors"
                          >
                            <KeyRound size={15} />
                          </button>
                          <button
                            onClick={() => del(u.id)}
                            title="Elimina utente"
                            className="p-1.5 rounded hover:bg-red-900/30 text-gray-400 hover:text-red-400 transition-colors"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Sicurezza accessi ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 pt-2">
        <ScrollText size={20} className="text-gold-500" />
        <h2 className="text-xl font-bold text-gray-100">Sicurezza accessi</h2>
      </div>

      {security && security.locked.length > 0 && (
        <div className="card border-red-500/40">
          <div className="flex items-center gap-2 mb-3">
            <ShieldAlert size={16} className="text-red-400" />
            <h3 className="text-sm font-semibold text-gray-200">
              Blocchi attivi ({security.locked.length})
            </h3>
          </div>
          <p className="text-xs text-gray-500 mb-3">
            Bloccati dopo {security.max_attempts} tentativi falliti; lo sblocco è automatico dopo {security.lockout_minutes} minuti senza nuovi tentativi.
          </p>
          <div className="space-y-2">
            {security.locked.map((l) => (
              <div key={`${l.type}:${l.value}`} className="flex items-center justify-between gap-3 text-sm bg-navy-900/40 rounded-lg px-3 py-2">
                <div className="min-w-0">
                  <span className={l.type === 'ip' ? 'badge-red' : 'badge-gold'}>
                    {l.type === 'ip' ? 'IP' : 'Account'}
                  </span>
                  <span className="font-mono text-gray-100 ml-2 break-all">{l.value}</span>
                  <span className="text-gray-600 text-xs ml-2">{l.fail_count} tentativi falliti</span>
                </div>
                <button
                  onClick={() => unlock(l)}
                  className="flex-shrink-0 flex items-center gap-1 px-3 py-1 rounded-lg bg-gold-500/15 text-gold-400 hover:bg-gold-500/25 text-xs font-medium transition-colors"
                >
                  <Unlock size={13} /> Sblocca
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-200">Registro accessi (ultimi 100)</h3>
          <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
            <input type="checkbox" checked={onlyFailed} onChange={toggleOnlyFailed} className="accent-gold-500" />
            Solo falliti
          </label>
        </div>
        {attempts.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">Nessun tentativo di accesso registrato.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700/50">
                  {['Data e ora', 'Esito', 'Identificativo', 'IP', 'Dispositivo'].map((h) => (
                    <th key={h} className="text-left py-2 pr-4 text-xs font-medium text-gray-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {attempts.map((a) => (
                  <tr key={a.id} className="table-row-hover border-b border-gray-700/20">
                    <td className="py-2.5 pr-4 text-gray-400 whitespace-nowrap">{fmtDateTime(a.created_at)}</td>
                    <td className="py-2.5 pr-4">
                      {a.success
                        ? <span className="badge-green">OK</span>
                        : a.blocked
                          ? <span className="badge-red">Bloccato</span>
                          : <span className="badge-red">Fallito</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-gray-200 break-all">{a.identifier || <span className="text-gray-600">—</span>}</td>
                    <td className="py-2.5 pr-4 font-mono text-gray-400 break-all">{a.ip_address || <span className="text-gray-600">—</span>}</td>
                    <td className="py-2.5 pr-4 text-gray-500 text-xs max-w-xs truncate" title={a.user_agent || ''}>
                      {a.user_agent || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {resetUser && (
        <div className="fixed inset-0 z-[70] bg-black/60 flex items-center justify-center p-4" onClick={() => setResetUser(null)}>
          <div className="card border-gray-700/60 w-full max-w-sm relative" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setResetUser(null)} className="absolute top-3 right-3 text-gray-500 hover:text-gray-300">
              <X size={18} />
            </button>
            <h2 className="text-base font-semibold text-gray-200 mb-1">Reset password</h2>
            <p className="text-xs text-gray-500 mb-4">
              Imposta una password temporanea per <span className="text-gray-300 font-medium">{resetUser.username}</span> e comunicagliela di persona. Potrà cambiarla dopo il login.
            </p>

            {resetDone ? (
              <div className="space-y-4">
                <div className="text-emerald-400 text-sm bg-emerald-900/20 border border-emerald-700/30 rounded-lg px-3 py-2">
                  Password reimpostata per {resetUser.username}.
                </div>
                <button onClick={() => setResetUser(null)} className="btn-primary w-full">Chiudi</button>
              </div>
            ) : (
              <form onSubmit={submitReset} className="space-y-4">
                <div>
                  <label className="label">Password temporanea</label>
                  <PasswordField
                    value={newPw}
                    onChange={setNewPw}
                    required
                    autoFocus
                    defaultVisible
                    onGenerate={() => setNewPw(generatePassword())}
                  />
                  <p className="text-xs text-gray-600 mt-1">Almeno 8 caratteri.</p>
                </div>
                {resetErr && (
                  <div className="text-red-400 text-sm bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{resetErr}</div>
                )}
                <button type="submit" disabled={resetLoading} className="btn-primary w-full">
                  {resetLoading ? 'Salvataggio...' : 'Imposta password'}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
