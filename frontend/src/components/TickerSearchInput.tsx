/**
 * TickerSearchInput
 *
 * Controlled input with a debounced Yahoo Finance typeahead dropdown.
 * The dropdown is rendered via a React portal (fixed-positioned) so it
 * escapes any parent overflow/clip container (e.g. scrollable table).
 *
 * Props:
 *   value          – controlled value (what's shown in the input)
 *   onChange       – called on every keystroke with the raw new value
 *   onSelect       – optional: called when user picks a result from the list
 *   placeholder
 *   inputClassName – full class string for the <input> element
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Loader2 } from 'lucide-react'
import { marketApi } from '../api'

// ── Types ────────────────────────────────────────────────────────────────────

export interface TickerResult {
  ticker: string
  name: string
  type: string
  exchange: string
}

interface Props {
  value: string
  onChange: (val: string) => void
  onSelect?: (result: TickerResult) => void
  placeholder?: string
  inputClassName?: string
}

// ── Type badge ────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  etf:           'bg-gold-500/15 text-gold-400 border-gold-500/25',
  equity:        'bg-blue-900/40 text-blue-300 border-blue-700/30',
  'mutual fund': 'bg-purple-900/40 text-purple-300 border-purple-700/30',
  bond:          'bg-teal-900/40 text-teal-300 border-teal-700/30',
}

function TypeBadge({ type }: { type: string }) {
  const key = (type ?? '').toLowerCase()
  const cls = TYPE_COLORS[key] ?? 'bg-gray-700/60 text-gray-400 border-gray-600/30'
  return (
    <span className={`inline-block border rounded px-1.5 py-px text-[9px] font-semibold uppercase ${cls}`}>
      {type || '?'}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TickerSearchInput({
  value,
  onChange,
  onSelect,
  placeholder = 'Cerca ticker o nome…',
  inputClassName = '',
}: Props) {
  const [suggestions, setSuggestions] = useState<TickerResult[]>([])
  const [searching, setSearching]     = useState(false)
  const [open, setOpen]               = useState(false)
  const [activeIdx, setActiveIdx]     = useState(-1)
  const [dropPos, setDropPos]         = useState({ top: 0, left: 0, width: 0 })

  const inputRef    = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Calculate fixed position of the dropdown below the input
  const calcPos = useCallback(() => {
    if (!inputRef.current) return
    const r = inputRef.current.getBoundingClientRect()
    setDropPos({ top: r.bottom + 2, left: r.left, width: r.width })
  }, [])

  // Debounced search
  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setSuggestions([]); setOpen(false); return }
    setSearching(true)
    try {
      const res = await marketApi.searchInstruments(q)
      const items: TickerResult[] = res.data ?? []
      setSuggestions(items)
      if (items.length > 0) { calcPos(); setOpen(true) }
      else setOpen(false)
      setActiveIdx(-1)
    } catch {
      setSuggestions([])
      setOpen(false)
    } finally {
      setSearching(false)
    }
  }, [calcPos])

  const handleChange = (val: string) => {
    onChange(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(val.trim()), 350)
  }

  const select = (s: TickerResult) => {
    setOpen(false)
    setSuggestions([])
    onChange(s.ticker)
    onSelect?.(s)
  }

  // Cleanup debounce on unmount
  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current) }, [])

  // Close on blur (delay lets click events on suggestions fire first)
  const handleBlur = () => setTimeout(() => setOpen(false), 150)

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || !suggestions.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      select(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  // Portal dropdown — fixed position escapes any overflow clipping
  const dropdown =
    open && suggestions.length > 0
      ? createPortal(
          <div
            style={{
              position: 'fixed',
              top:      dropPos.top,
              left:     dropPos.left,
              minWidth: Math.max(dropPos.width, 320),
              zIndex:   9999,
            }}
            className="bg-navy-800 border border-gray-600/60 rounded-lg shadow-2xl overflow-hidden"
            // Prevent the input from blurring when user clicks a suggestion
            onMouseDown={e => e.preventDefault()}
          >
            {suggestions.map((s, idx) => (
              <button
                key={`${s.ticker}-${idx}`}
                type="button"
                onClick={() => select(s)}
                className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors ${
                  idx === activeIdx ? 'bg-navy-600' : 'hover:bg-navy-700'
                }`}
              >
                <span className="font-mono font-bold text-gray-100 text-xs w-20 flex-shrink-0 truncate">
                  {s.ticker}
                </span>
                <span className="flex-1 text-xs text-gray-400 truncate">{s.name}</span>
                <span className="flex-shrink-0 flex items-center gap-1.5">
                  <TypeBadge type={s.type} />
                  <span className="text-[9px] text-gray-600 w-10 text-right truncate">{s.exchange}</span>
                </span>
              </button>
            ))}
          </div>,
          document.body
        )
      : null

  return (
    <div className="relative">
      <input
        ref={inputRef}
        className={inputClassName}
        placeholder={placeholder}
        value={value}
        onChange={e => handleChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onFocus={() => { if (value.length >= 2 && suggestions.length > 0) { calcPos(); setOpen(true) } }}
        autoComplete="off"
        spellCheck={false}
      />
      {searching && (
        <Loader2
          size={12}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-gray-400 pointer-events-none"
        />
      )}
      {dropdown}
    </div>
  )
}
