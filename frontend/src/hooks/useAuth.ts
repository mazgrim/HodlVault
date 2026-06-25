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
  login: (username: string, password: string) => Promise<void>
  loginDemo: () => Promise<void>
  logout: () => void
  register: (username: string, email: string, password: string) => Promise<void>
}

export const AuthContext = createContext<AuthCtx>({} as AuthCtx)

export function useAuth() {
  return useContext(AuthContext)
}

export function useAuthProvider(): AuthCtx {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (token) {
      authApi.me()
        .then((r) => setUser(r.data))
        .catch(() => {
          localStorage.clear()
          setUser(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
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

  const isDemo = user?.username === 'demo'

  return { user, loading, isDemo, login, loginDemo, logout, register }
}
