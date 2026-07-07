import { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, TrendingUp, PieChart, Landmark,
  Upload, Wrench, LogOut, ChevronLeft, ChevronRight,
  Users, RefreshCw, History, Menu, ArrowLeftRight, BarChart2,
  Sun, Moon, KeyRound, User, ChevronUp, ChevronDown, DatabaseBackup,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'
import { marketApi, adminApi } from '../api'
import ChangePasswordModal from './ChangePasswordModal'

const NAV = [
  { to: '/',              icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/performance',   icon: TrendingUp,      label: 'Performance' },
  { to: '/benchmark',    icon: BarChart2,        label: 'Benchmark' },
  { to: '/analysis',      icon: PieChart,        label: 'Analisi' },
  { to: '/dividends',     icon: Landmark,        label: 'Dividendi' },
  { to: '/transactions',  icon: ArrowLeftRight,  label: 'Transazioni' },
  { to: '/import',        icon: Upload,          label: 'Importa' },
  { to: '/backup',        icon: DatabaseBackup,  label: 'Backup' },
  { to: '/tools',         icon: Wrench,          label: 'Tools' },
]

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { user, logout, isDemo, desktopMode } = useAuth()
  const { theme, toggleTheme } = useTheme()
  // In desktop mode (single-user, passwordless) admin / cambio password / logout
  // non hanno senso: nascosti.
  const showAdmin = !!user?.is_admin && !desktopMode
  const showChangePassword = !isDemo && !desktopMode
  const showLogout = !desktopMode
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [showChangePw, setShowChangePw] = useState(false)
  const [pendingResets, setPendingResets] = useState(0)
  const [accountOpen, setAccountOpen] = useState(false)

  // Close the account menu when clicking outside it. Uses a data-attribute lookup
  // (not a ref) because the sidebar markup is rendered twice (desktop + mobile):
  // a single ref would point at the wrong instance and dismiss the menu on mousedown
  // before the item's click could fire — leaving the menu closed but the action lost.
  useEffect(() => {
    if (!accountOpen) return
    const onDown = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('[data-account-menu]')) setAccountOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [accountOpen])

  // Admin notification: count of pending password-reset requests for the badge.
  useEffect(() => {
    if (!showAdmin) { setPendingResets(0); return }
    adminApi.passwordRequests()
      .then((r) => setPendingResets(r.data.length))
      .catch(() => {})
  }, [showAdmin])

  // Foreground progress bar + percentage badge for the market-data actions, so the
  // user sees that something is happening even when the request is near-instant.
  const [barLabel, setBarLabel] = useState('')
  const [barVisible, setBarVisible] = useState(false)
  const [barProgress, setBarProgress] = useState(0)
  const running = refreshing || loadingHistory

  useEffect(() => {
    let ramp: ReturnType<typeof setInterval> | undefined
    let hide: ReturnType<typeof setTimeout> | undefined
    if (running) {
      setBarVisible(true)
      setBarProgress((p) => (p < 8 ? 8 : p))
      // Ease quickly toward 90% while the request is pending (never reaches 100).
      ramp = setInterval(() => setBarProgress((p) => (p < 90 ? p + (90 - p) * 0.2 : p)), 150)
    } else if (barVisible) {
      // Snap to 100%, then fade out.
      setBarProgress(100)
      hide = setTimeout(() => { setBarVisible(false); setBarProgress(0) }, 500)
    }
    return () => { if (ramp) clearInterval(ramp); if (hide) clearTimeout(hide) }
  }, [running])  // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the action "running" for at least ~700ms so the progress animation is
  // always visible, even when the backend responds almost instantly.
  const withMinTime = async (fn: () => Promise<unknown>) => {
    const start = Date.now()
    try { await fn() } finally {
      const rest = 700 - (Date.now() - start)
      if (rest > 0) await new Promise((r) => setTimeout(r, rest))
    }
  }

  const handleRefresh = async () => {
    setBarLabel('Aggiornamento prezzi')
    setRefreshing(true)
    try { await withMinTime(() => marketApi.refreshPrices()) } finally { setRefreshing(false) }
  }

  const handleLoadHistory = async () => {
    setBarLabel('Caricamento storico')
    setLoadingHistory(true)
    try { await withMinTime(() => marketApi.refreshHistory()) } finally { setLoadingHistory(false) }
  }

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className={`flex items-center border-b border-gray-700/40 ${collapsed ? 'justify-center px-2 py-3' : 'flex-col px-3 py-4'}`}>
        {collapsed ? (
          <img src="/hodlvault_logo.svg" alt="HodlVault" className="w-10 h-10 object-contain" />
        ) : (
          <>
            <img src="/hodlvault_logo.svg" alt="HodlVault" className="w-16 h-16 object-contain" />
            <div className="mt-2 text-center">
              <div className="text-gold-400 font-bold tracking-[0.25em] text-base" style={{ fontFamily: 'Georgia, serif' }}>HODL VAULT</div>
              <div className="text-gold-600 tracking-[0.15em] text-[10px] mt-0.5" style={{ fontFamily: 'Georgia, serif' }}>Portfolio Tracker</div>
            </div>
          </>
        )}
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                isActive
                  ? 'bg-gold-500/15 text-gold-500 border border-gold-500/25'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-navy-700/60'
              } ${collapsed ? 'justify-center' : ''}`
            }
          >
            <Icon size={18} className="flex-shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Bottom actions */}
      <div className="px-2 py-4 border-t border-gray-700/40 space-y-1">
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          title="Aggiorna prezzi"
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-gold-400 hover:bg-navy-700/60 transition-all w-full ${collapsed ? 'justify-center' : ''}`}
        >
          <RefreshCw size={18} className={`flex-shrink-0 ${refreshing ? 'animate-spin text-gold-500' : ''}`} />
          {!collapsed && <span>{refreshing ? 'Aggiornamento...' : 'Aggiorna prezzi'}</span>}
        </button>
        <button
          onClick={handleLoadHistory}
          disabled={loadingHistory}
          title="Carica storico prezzi"
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-gold-400 hover:bg-navy-700/60 transition-all w-full ${collapsed ? 'justify-center' : ''}`}
        >
          <History size={18} className={`flex-shrink-0 ${loadingHistory ? 'animate-pulse text-gold-500' : ''}`} />
          {!collapsed && <span>{loadingHistory ? 'Caricamento...' : 'Carica storico'}</span>}
        </button>
        {collapsed ? (
          <>
            {showAdmin && (
              <NavLink
                to="/admin" onClick={() => setMobileOpen(false)} title="Amministrazione"
                className={({ isActive }) =>
                  `relative flex items-center justify-center px-3 py-2.5 rounded-lg transition-all w-full ${
                    isActive ? 'bg-gold-500/15 text-gold-500' : 'text-gray-400 hover:text-gold-400 hover:bg-navy-700/60'
                  }`
                }
              >
                <Users size={18} />
                {pendingResets > 0 && <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500" />}
              </NavLink>
            )}
            {showChangePassword && (
              <button onClick={() => setShowChangePw(true)} title="Cambia password"
                className="flex items-center justify-center px-3 py-2.5 rounded-lg text-gray-400 hover:text-gold-400 hover:bg-navy-700/60 transition-all w-full">
                <KeyRound size={18} />
              </button>
            )}
            <button onClick={toggleTheme} title={theme === 'dark' ? 'Tema chiaro' : 'Tema scuro'}
              className="flex items-center justify-center px-3 py-2.5 rounded-lg text-gray-400 hover:text-gold-400 hover:bg-navy-700/60 transition-all w-full">
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            {showLogout && (
              <button onClick={logout} title="Esci"
                className="flex items-center justify-center px-3 py-2.5 rounded-lg text-gray-400 hover:text-red-400 hover:bg-red-900/20 transition-all w-full">
                <LogOut size={18} />
              </button>
            )}
          </>
        ) : (
          <div className="relative" data-account-menu>
            {accountOpen && (
              <div className="absolute bottom-full left-0 right-0 mb-1 rounded-lg bg-navy-700 border border-gray-700/60 shadow-xl py-1 z-20">
                {showAdmin && (
                  <NavLink
                    to="/admin" onClick={() => { setAccountOpen(false); setMobileOpen(false) }}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2 text-sm w-full transition-colors ${
                        isActive ? 'text-gold-500' : 'text-gray-300 hover:text-gold-400 hover:bg-navy-600/60'
                      }`
                    }
                  >
                    <Users size={16} className="flex-shrink-0" />
                    <span>Admin</span>
                    {pendingResets > 0 && (
                      <span className="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold">
                        {pendingResets}
                      </span>
                    )}
                  </NavLink>
                )}
                {showChangePassword && (
                  <button onClick={() => { setAccountOpen(false); setShowChangePw(true) }}
                    className="flex items-center gap-3 px-3 py-2 text-sm w-full text-gray-300 hover:text-gold-400 hover:bg-navy-600/60 transition-colors">
                    <KeyRound size={16} className="flex-shrink-0" />
                    <span>Cambia password</span>
                  </button>
                )}
                <button onClick={() => { setAccountOpen(false); toggleTheme() }}
                  className="flex items-center gap-3 px-3 py-2 text-sm w-full text-gray-300 hover:text-gold-400 hover:bg-navy-600/60 transition-colors">
                  {theme === 'dark' ? <Sun size={16} className="flex-shrink-0" /> : <Moon size={16} className="flex-shrink-0" />}
                  <span>{theme === 'dark' ? 'Tema chiaro' : 'Tema scuro'}</span>
                </button>
                {showLogout && (
                  <button onClick={() => { setAccountOpen(false); logout() }}
                    className="flex items-center gap-3 px-3 py-2 text-sm w-full text-gray-300 hover:text-red-400 hover:bg-red-900/20 transition-colors">
                    <LogOut size={16} className="flex-shrink-0" />
                    <span>Esci</span>
                  </button>
                )}
              </div>
            )}
            <button onClick={() => setAccountOpen((o) => !o)}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-300 hover:bg-navy-700/60 transition-all w-full">
              <User size={18} className="flex-shrink-0" />
              <span className="truncate flex-1 text-left">{user?.username}</span>
              {pendingResets > 0 && !accountOpen && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex-shrink-0">
                  {pendingResets}
                </span>
              )}
              {accountOpen ? <ChevronUp size={16} className="flex-shrink-0" /> : <ChevronDown size={16} className="flex-shrink-0" />}
            </button>
          </div>
        )}
      </div>

      {/* Collapse toggle (desktop) */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="hidden lg:flex items-center justify-center absolute -right-3 top-20 w-6 h-6 rounded-full bg-navy-700 border border-gray-600 text-gray-400 hover:text-gray-200 transition-colors"
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>
    </>
  )

  return (
    <div className="flex h-screen bg-navy-900 overflow-hidden">
      {showChangePw && <ChangePasswordModal onClose={() => setShowChangePw(false)} />}

      {/* Foreground progress bar + percentage badge for market-data actions */}
      {barVisible && (
        <>
          <div className="fixed top-0 left-0 right-0 z-[60] h-1 pointer-events-none">
            <div
              className="h-full bg-gold-500 shadow-[0_0_8px_rgba(212,160,23,0.7)] transition-[width] duration-200 ease-out"
              style={{ width: `${barProgress}%` }}
            />
          </div>
          <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[60] flex items-center gap-2 px-3 py-1.5 rounded-full bg-navy-800 border border-gold-500/40 shadow-lg text-xs font-medium text-gold-300 pointer-events-none">
            <RefreshCw size={13} className="animate-spin flex-shrink-0" />
            <span>{barLabel} {Math.round(barProgress)}%</span>
          </div>
        </>
      )}

      {/* Desktop sidebar */}
      <aside
        className={`hidden lg:flex flex-col relative bg-navy-800 border-r border-gray-700/40 transition-all duration-200 flex-shrink-0 ${
          collapsed ? 'w-16' : 'w-56'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/60 z-40"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile sidebar */}
      <aside
        className={`lg:hidden fixed inset-y-0 left-0 z-50 flex flex-col w-56 bg-navy-800 border-r border-gray-700/40 transform transition-transform duration-200 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile top bar */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3 bg-navy-800 border-b border-gray-700/40">
          <button onClick={() => setMobileOpen(true)} className="text-gray-400 hover:text-gray-200">
            <Menu size={22} />
          </button>
          <img src="/hodlvault_logo.svg" alt="HodlVault" className="h-9 w-auto" />
        </header>

        {isDemo && (
          <div className="flex items-center justify-center gap-2 px-4 py-2 bg-gold-500/10 border-b border-gold-500/20 text-gold-400 text-xs font-medium flex-shrink-0">
            <span>🚀</span>
            <span>Modalità Demo — sola lettura · I dati sono simulati e non persistono</span>
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
