import api from './client'

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),
  register: (username: string, email: string, password: string) =>
    api.post('/auth/register', { username, email, password }),
  me: () => api.get('/auth/me'),
  config: () => api.get('/auth/config'),
  desktopLogin: () => api.post('/auth/desktop-login'),
  desktopSetup: (username: string) => api.post('/auth/desktop-setup', { username }),
  refresh: (refresh_token: string) =>
    api.post('/auth/refresh', { refresh_token }),
  changePassword: (old_password: string, new_password: string) =>
    api.post('/auth/change-password', { old_password, new_password }),
  forgotPassword: (identifier: string) =>
    api.post('/auth/forgot-password', { identifier }),
}

// ── Portfolios ────────────────────────────────────────────────────────────────
export const portfolioApi = {
  list: () => api.get('/portfolios/'),
  create: (data: { name: string; broker?: string; currency?: string }) =>
    api.post('/portfolios/', data),
  update: (id: number, data: object) => api.put(`/portfolios/${id}`, data),
  delete: (id: number) => api.delete(`/portfolios/${id}`),
}

// ── Transactions ──────────────────────────────────────────────────────────────
export const txApi = {
  list: (portfolio_id?: number) =>
    api.get('/transactions/', { params: portfolio_id ? { portfolio_id } : {} }),
  create: (data: object) => api.post('/transactions/', data),
  update: (id: number, data: object) => api.put(`/transactions/${id}`, data),
  delete: (id: number) => api.delete(`/transactions/${id}`),
}

// ── Dashboard / Market ────────────────────────────────────────────────────────
export const marketApi = {
  kpis: (portfolio_id?: number) =>
    api.get('/market/dashboard/kpis', { params: portfolio_id ? { portfolio_id } : {} }),
  positions: (portfolio_id?: number) =>
    api.get('/market/dashboard/positions', { params: portfolio_id ? { portfolio_id } : {} }),
  closedPositions: (portfolio_id?: number) =>
    api.get('/market/dashboard/closed-positions', { params: portfolio_id ? { portfolio_id } : {} }),
  chart: (portfolio_id?: number, period = '1Y') =>
    api.get('/market/dashboard/chart', { params: { period, ...(portfolio_id ? { portfolio_id } : {}) } }),
  analysis: (portfolio_id?: number) =>
    api.get('/market/analysis', { params: portfolio_id ? { portfolio_id } : {} }),
  searchInstruments: (q: string) =>
    api.get('/market/instruments/search', { params: { q } }),
  refreshPrices: () => api.post('/market/refresh'),
  refreshHistory: () => api.post('/market/refresh-history'),
  instruments: () => api.get('/market/instruments'),
  lookupInstrument: (params: { isin?: string; ticker?: string }) =>
    api.get('/market/instruments/lookup', { params }),
  fxRates: (pair?: string) =>
    api.get('/market/fx-rates', { params: pair ? { pair } : {} }),
  createInstrument: (data: object) => api.post('/market/instruments', data),
  updateInstrument: (id: number, data: object) => api.patch(`/market/instruments/${id}`, data),
  instrumentDetail: (id: number) =>
    api.get(`/market/instruments/${id}/detail`),
  instrumentPriceChart: (id: number, period: string) =>
    api.get(`/market/instruments/${id}/price-chart`, { params: { period } }),
  // Fonti prezzo alternative a Yahoo
  addManualPrice: (id: number, data: { date: string; price: number }) =>
    api.post(`/market/instruments/${id}/prices`, data),
  deleteManualPrice: (id: number, date: string) =>
    api.delete(`/market/instruments/${id}/prices/${date}`),
  testCustomSource: (data: {
    url: string; jsonpath_price: string; jsonpath_date?: string | null
    isin?: string | null; ticker?: string | null
  }) => api.post('/market/instruments/custom-source/test', data),
  refreshInstrumentPrice: (id: number) =>
    api.post(`/market/instruments/${id}/refresh-price`),
}

// ── Cedole (piano cedolare certificati) ───────────────────────────────────────
export const couponApi = {
  list: (instrument_id: number) =>
    api.get('/coupons/', { params: { instrument_id } }),
  upcoming: (portfolio_id?: number) =>
    api.get('/coupons/upcoming', { params: portfolio_id ? { portfolio_id } : {} }),
  create: (data: object) => api.post('/coupons/', data),
  bulk: (rows: object[]) => api.post('/coupons/bulk', rows),
  update: (id: number, data: object) => api.put(`/coupons/${id}`, data),
  delete: (id: number) => api.delete(`/coupons/${id}`),
  confirm: (id: number, data: { portfolio_id: number; gross_amount: number; date?: string; tax_amount?: number; minus_compensation?: boolean }) =>
    api.post(`/coupons/${id}/confirm`, data),
  skip: (id: number) => api.post(`/coupons/${id}/skip`),
  reset: (id: number) => api.post(`/coupons/${id}/reset`),
}

// ── Performance ───────────────────────────────────────────────────────────────
export const perfApi = {
  metrics: (portfolio_id?: number, benchmark = 'SWDA.MI') =>
    api.get('/performance/kpis', { params: { benchmark, ...(portfolio_id ? { portfolio_id } : {}) } }),
  monthlyReturns: (portfolio_id?: number) =>
    api.get('/performance/monthly-returns', { params: portfolio_id ? { portfolio_id } : {} }),
  drawdown: (portfolio_id?: number) =>
    api.get('/performance/drawdown', { params: portfolio_id ? { portfolio_id } : {} }),
  cumulative: (portfolio_id?: number, benchmark = 'SWDA.MI', period = '1Y') =>
    api.get('/performance/cumulative', { params: { benchmark, period, ...(portfolio_id ? { portfolio_id } : {}) } }),
}

// ── Dividends ─────────────────────────────────────────────────────────────────
export const divApi = {
  list: (portfolio_id?: number) =>
    api.get('/dividends/', { params: portfolio_id ? { portfolio_id } : {} }),
  create: (data: object) => api.post('/dividends/', data),
  delete: (id: number) => api.delete(`/dividends/${id}`),
  toggleMinus: (id: number, minus_compensation: boolean) =>
    api.patch(`/dividends/${id}/minus-compensation`, { minus_compensation }),
  sync: (portfolio_id?: number) =>
    api.post('/dividends/sync', null, { params: portfolio_id ? { portfolio_id } : {} }),
  kpis: (portfolio_id?: number) =>
    api.get('/dividends/kpis', { params: portfolio_id ? { portfolio_id } : {} }),
  monthly: (portfolio_id?: number) =>
    api.get('/dividends/monthly', { params: portfolio_id ? { portfolio_id } : {} }),
  projection: (portfolio_id?: number) =>
    api.get('/dividends/projection', { params: portfolio_id ? { portfolio_id } : {} }),
}

// ── Import ────────────────────────────────────────────────────────────────────
export const importApi = {
  preview: (file: File, broker: string, portfolio_id: number) => {
    const form = new FormData()
    form.append('file', file)
    form.append('broker', broker)
    form.append('portfolio_id', String(portfolio_id))
    return api.post('/import/preview', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  confirm: (data: object) => api.post('/import/confirm', data),
}

// ── Backup / Ripristino ─────────────────────────────────────────────────────
export const backupApi = {
  exportJson: () => api.get('/backup/export', { responseType: 'blob' }),
  exportXlsx: () => api.get('/backup/export.xlsx', { responseType: 'blob' }),
  exportCsv: () => api.get('/backup/export.csv', { responseType: 'blob' }),
  importPreview: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/backup/import/preview', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  importConfirm: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/backup/import', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
}

// ── Admin ─────────────────────────────────────────────────────────────────────
export const adminApi = {
  users: () => api.get('/admin/users'),
  updateUser: (id: number, data: object) => api.patch(`/admin/users/${id}`, data),
  deleteUser: (id: number) => api.delete(`/admin/users/${id}`),
  passwordRequests: () => api.get('/admin/password-requests'),
  resetPassword: (userId: number, newPassword: string) =>
    api.post(`/admin/users/${userId}/reset-password`, { new_password: newPassword }),
  loginAttempts: (params?: { limit?: number; only_failed?: boolean }) =>
    api.get('/admin/login-attempts', { params }),
  securityStatus: () => api.get('/admin/security/status'),
  clearLockout: (data: { ip_address?: string; identifier?: string }) =>
    api.post('/admin/security/clear-lockout', data),
}

// ── Benchmark ─────────────────────────────────────────────────────────────────
export const benchmarkApi = {
  available: () => api.get('/benchmark/available'),
  chart: (tickers: string[], period: string, portfolio_id?: number, mode: string = 'twr', exclude: number[] = []) =>
    api.get('/benchmark/chart', {
      params: {
        tickers: tickers.join(','), period, mode,
        ...(exclude.length ? { exclude: exclude.join(',') } : {}),
        ...(portfolio_id ? { portfolio_id } : {}),
      },
    }),
}

// ── Demo ──────────────────────────────────────────────────────────────────────
export const demoApi = {
  login: () => api.post('/demo/login'),
}

// ── Tools ─────────────────────────────────────────────────────────────────────
export const toolsApi = {
  compound: (data: object) => api.post('/tools/compound', data),
  pacVsLumpsum: (data: object) => api.post('/tools/pac-vs-lumpsum', data),
  inflation: (data: object) => api.post('/tools/inflation', data),
}
