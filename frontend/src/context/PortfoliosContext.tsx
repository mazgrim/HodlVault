import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { portfolioApi } from '../api'

export interface Portfolio {
  id: number
  name: string
  broker: string | null
  currency: string
  created_at: string
}

interface PortfoliosContextValue {
  portfolios: Portfolio[]
  loading: boolean
  reload: () => void
}

const PortfoliosContext = createContext<PortfoliosContextValue>({
  portfolios: [],
  loading: true,
  reload: () => {},
})

export function PortfoliosProvider({ children }: { children: ReactNode }) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const res = await portfolioApi.list()
      setPortfolios(res.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <PortfoliosContext.Provider value={{ portfolios, loading, reload: load }}>
      {children}
    </PortfoliosContext.Provider>
  )
}

export const usePortfolios = () => useContext(PortfoliosContext)
