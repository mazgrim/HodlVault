import { ReactNode } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'

interface Props {
  title: string
  value: string
  subtitle?: string
  trend?: number       // shows colored % badge + colors value text
  colorByValue?: number // only colors value text, no badge
  icon?: ReactNode
  gold?: boolean
  compact?: boolean    // uses text-xl instead of text-2xl (for long currency values)
  center?: boolean     // centers title/value/subtitle (no icon row), matches dashboard layout
}

export default function KpiCard({ title, value, subtitle, trend, colorByValue, icon, gold, compact, center }: Props) {
  const borderClass = gold ? 'border-gold-500/50 shadow-gold-500/10 shadow-lg' : 'border-gray-700/40'
  const isPositive = trend !== undefined ? trend > 0 : colorByValue !== undefined ? colorByValue > 0 : false
  const isNegative = trend !== undefined ? trend < 0 : colorByValue !== undefined ? colorByValue < 0 : false
  const hasColor    = trend !== undefined || colorByValue !== undefined

  return (
    <div className={`card ${borderClass} flex flex-col gap-2 ${center ? 'items-center text-center' : ''}`}>
      <div className={`flex items-center gap-2 w-full ${center ? 'justify-center' : 'justify-between'}`}>
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">{title}</span>
        {icon && !center && <span className="text-gray-500">{icon}</span>}
      </div>
      <div className={`flex items-end gap-2 min-w-0 ${center ? 'justify-center' : 'justify-between'}`}>
        <span
          className={`${compact ? 'text-lg sm:text-xl' : 'text-xl sm:text-2xl'} font-bold tabular-nums min-w-0 ${
            hasColor
              ? (isPositive ? 'text-emerald-400' : isNegative ? 'text-red-400' : 'text-gray-400')
              : 'text-gray-100'
          }`}
        >
          {value}
        </span>
        {trend !== undefined && (
          <span className={`flex items-center gap-0.5 text-sm font-medium mb-0.5 flex-shrink-0 ${isPositive ? 'text-emerald-400' : isNegative ? 'text-red-400' : 'text-gray-400'}`}>
            {isPositive ? <TrendingUp size={14} /> : isNegative ? <TrendingDown size={14} /> : null}
            {trend > 0 ? '+' : ''}{trend.toFixed(2)}%
          </span>
        )}
      </div>
      {subtitle && <span className="text-xs text-gray-500">{subtitle}</span>}
    </div>
  )
}
