import { useState, useEffect } from 'react'
import { adminApi } from '../api'
import { fmtDate } from '../utils/format'
import { useAuth } from '../hooks/useAuth'
import { Shield, UserCheck, UserX, Trash2 } from 'lucide-react'
import { PageSpinner } from '../components/Spinner'

interface User { id: number; username: string; email: string; is_active: boolean; is_admin: boolean; created_at: string }

export default function Admin() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try { const r = await adminApi.users(); setUsers(r.data) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

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
    </div>
  )
}
