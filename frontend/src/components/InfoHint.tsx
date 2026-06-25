import { Info } from 'lucide-react'

interface Props {
  text: string
}

/**
 * Small "i" icon that reveals an explanatory tooltip on hover/focus.
 * Used to document how a metric (Sharpe, volatility, …) is computed.
 */
export default function InfoHint({ text }: Props) {
  return (
    <span className="group relative inline-flex items-center">
      <Info
        size={14}
        tabIndex={0}
        className="text-gray-500 hover:text-gray-300 focus:text-gray-300 cursor-help outline-none transition-colors"
      />
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-20 mt-2 w-64
                   rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-normal normal-case
                   leading-relaxed tracking-normal text-gray-200 shadow-xl
                   opacity-0 transition-opacity duration-150
                   group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {text}
      </span>
    </span>
  )
}
