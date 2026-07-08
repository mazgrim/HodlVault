import { useState, useEffect, createContext, useContext } from 'react'
import { authApi, demoApi } from '../api'

export interface User {
  id: number
  username: string
  email: string
  is_admin: boolean
  is_active: boolean
}

interface AuthCtx {
  user: User | null
  loading: boolean
  isDemo: boolean
  desktopMode: boolean
  needsSetup: boolean
  login: (username: string, password: string) => Promise<void>
  loginDemo: () => Promise<void>
  logout: () => void
  register: (username: string, email: string, password: string) => Promise<void>
  desktopSetup: (username: string) => Promise<void>
}

export const AuthContext = createContext<AuthCtx>({} as AuthCtx)

export function useAuth() {
  return useContext(AuthContext)
}

export function useAuthProvider(): AuthCtx {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [desktopMode, setDesktopMode] = useState(false)
  const [needsSetup, setNeedsSetup] = useState(false)

  const storeTokensAndLoadUser = async (data: { access_token: string; refresh_token: string }) => {
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    const me = await authApi.me()
    setUser(me.data)
  }

  useEffect(() => {
    (async () => {
      // Legge sempre la config: serve a sapere se è desktop mode (per l'auto-login
      // e per nascondere le funzioni admin) anche quando un token è già presente.
      let cfg: { desktop_mode?: boolean; needs_setup?: boolean } | null = null
      try { cfg = (await authApi.config()).data } catch { /* offline: prosegui */ }
      if (cfg?.desktop_mode) setDesktopMode(true)

      const token = localStorage.getItem('access_token')
      if (token) {
        try { const me = await authApi.me(); setUser(me.data) }
        catch { localStorage.clear(); setUser(null) }
        setLoading(false)
        return
      }

      // Nessun token.
      if (cfg?.desktop_mode) {
        if (cfg.needs_setup) {
          // Primo avvio: mostra la schermata di scelta del nome utente.
          setNeedsSetup(true)
        } else {
          // Auto-login passwordless single-user.
          try { await storeTokensAndLoadUser((await authApi.desktopLogin()).data) }
          catch { /* fallback: resta senza sessione */ }
        }
      }
      setLoading(false)
    })()
  }, [])

  const login = async (username: string, password: string) => {
    const res = await authApi.login(username, password)
    localStorage.setItem('access_token', res.data.access_token)
    localStorage.setItem('refresh_token', res.data.refresh_token)
    const me = await authApi.me()
    setUser(me.data)
  }

  const logout = () => {
    localStorage.clear()
    setUser(null)
    window.location.href = '/login'
  }

  const register = async (username: string, email: string, password: string) => {
    await authApi.register(username, email, password)
    await login(username, password)
  }

  const loginDemo = async () => {
    const res = await demoApi.login()
    localStorage.setItem('access_token', res.data.access_token)
    localStorage.setItem('refresh_token', res.data.refresh_token)
    const me = await authApi.me()
    setUser(me.data)
  }

  const desktopSetup = async (username: string) => {
    await storeTokensAndLoadUser((await authApi.desktopSetup(username)).data)
    setNeedsSetup(false)
  }

  const isDemo = user?.username === 'demo'

  return { user, loading, isDemo, desktopMode, needsSetup, login, loginDemo, logout, register, desktopSetup }
}
