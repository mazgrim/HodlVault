import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthContext, useAuthProvider } from './hooks/useAuth'
import { PortfoliosProvider } from './context/PortfoliosContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Performance from './pages/Performance'
import Analysis from './pages/Analysis'
import Dividends from './pages/Dividends'
import Import from './pages/Import'
import DesktopSetup from './pages/DesktopSetup'
import Backup from './pages/Backup'
import Tools from './pages/Tools'
import Admin from './pages/Admin'
import Transactions from './pages/Transactions'
import InstrumentDetail from './pages/InstrumentDetail'
import Benchmark from './pages/Benchmark'
import { PageSpinner } from './components/Spinner'

function RequireAuth() {
  const token = localStorage.getItem('access_token')
  return token ? <Outlet /> : <Navigate to="/login" replace />
}

function App() {
  const auth = useAuthProvider()

  if (auth.loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-navy-900">
        <PageSpinner />
      </div>
    )
  }

  // Primo avvio dell'app desktop: scelta del nome utente prima di tutto.
  if (auth.needsSetup) {
    return (
      <AuthContext.Provider value={auth}>
        <DesktopSetup />
      </AuthContext.Provider>
    )
  }

  return (
    <AuthContext.Provider value={auth}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          {/* Layout wrapper */}
          <Route element={<RequireAuth />}>
            <Route element={<PortfoliosProvider><Layout><Outlet /></Layout></PortfoliosProvider>}>
              <Route index element={<Dashboard />} />
              <Route path="performance" element={<Performance />} />
              <Route path="analysis"    element={<Analysis />} />
              <Route path="dividends"   element={<Dividends />} />
              <Route path="transactions" element={<Transactions />} />
              <Route path="import"      element={<Import />} />
              <Route path="backup"      element={<Backup />} />
              <Route path="tools"       element={<Tools />} />
              <Route path="benchmark"   element={<Benchmark />} />
              <Route path="admin"       element={<Admin />} />
              <Route path="instruments/:id" element={<InstrumentDetail />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  )
}

export default App
