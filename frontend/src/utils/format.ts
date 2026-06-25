// Italian number formatting: 1.234,56 €
const IT_NUM = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const IT_INT = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0 })
const IT_PCT = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function fmtCurrency(value: number, currency = 'EUR'): string {
  const symbol = currency === 'EUR' ? '€' : currency === 'USD' ? '$' : currency === 'GBP' ? '£' : currency
  return `${symbol} ${IT_NUM.format(value)}`
}

export function fmtEur(value: number): string {
  return `€ ${IT_NUM.format(value)}`
}

export function fmtPct(value: number, plusSign = false): string {
  const s = `${IT_PCT.format(value)}%`
  return plusSign && value > 0 ? `+${s}` : s
}

export function fmtNum(value: number, decimals = 2): string {
  return new Intl.NumberFormat('it-IT', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

export function fmtQty(value: number): string {
  if (Number.isInteger(value)) return IT_INT.format(value)
  return new Intl.NumberFormat('it-IT', { maximumFractionDigits: 6 }).format(value)
}

export function fmtDate(d: string | Date): string {
  const date = typeof d === 'string' ? new Date(d) : d
  return new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date)
}

export function fmtMonth(yearMonth: string): string {
  // "2024-03" -> "Mar 2024"
  const [year, month] = yearMonth.split('-')
  const d = new Date(parseInt(year), parseInt(month) - 1, 1)
  return new Intl.DateTimeFormat('it-IT', { month: 'short', year: 'numeric' }).format(d)
}

export const MONTH_NAMES = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']

export function pnlClass(value: number): string {
  if (value > 0) return 'kpi-positive'
  if (value < 0) return 'kpi-negative'
  return 'text-gray-400'
}

export function pnlSign(value: number): string {
  return value > 0 ? '+' : ''
}
