import { useTheme } from '../hooks/useTheme'

/**
 * Theme-aware styling for Recharts components. Recharts is configured via inline
 * style props (contentStyle, stroke, fill) which cannot read CSS variables, so we
 * resolve concrete values from the active theme here.
 */
export function useChartTheme() {
  const { theme } = useTheme()
  const dark = theme === 'dark'

  /** Tooltip box style. `accent` controls the border hue (gold by default). */
  const tooltip = (accent: 'gold' | 'red' = 'gold') => ({
    background: dark ? '#13131f' : '#ffffff',
    border: `1px solid ${accent === 'red' ? 'rgba(239,68,68,0.3)' : 'rgba(212,160,23,0.3)'}`,
    borderRadius: 8,
    color: dark ? '#f3f4f6' : '#111827',
    boxShadow: dark ? 'none' : '0 4px 12px rgba(15,23,42,0.12)',
  })

  /** Readable text color for tooltip rows (use as itemStyle/labelStyle).
   *  Needed e.g. for pie tooltips, where Recharts would otherwise color the
   *  text with the slice color and make it unreadable on the dark popup. */
  const tooltipText = { color: dark ? '#e5e7eb' : '#111827' }

  /** Hover cursor for bar charts. Recharts' default is a light grey block that
   *  looks like a white background on the dark theme — use a subtle highlight. */
  const barCursor = { fill: dark ? 'rgba(255,255,255,0.06)' : 'rgba(15,23,42,0.06)' }

  return {
    dark,
    /** Cartesian grid line color */
    grid: dark ? '#1f2937' : '#e2e8f0',
    barCursor,
    /** Axis tick label color */
    axisTick: dark ? '#9ca3af' : '#64748b',
    /** Neutral series color (e.g. "invested"/"contributed" lines) */
    neutralSeries: dark ? '#374151' : '#cbd5e1',
    tooltip,
    tooltipText,
  }
}
