import { Portfolio } from '../context/PortfoliosContext'

interface Props {
  portfolios: Portfolio[]
  selected: number | null
  onChange: (id: number | null) => void
}

export default function PortfolioSelector({ portfolios, selected, onChange }: Props) {
  return (
    <select
      className="input max-w-xs text-sm"
      value={selected ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    >
      <option value="">Tutti i portafogli</option>
      {portfolios.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}{p.broker ? ` — ${p.broker}` : ''}
        </option>
      ))}
    </select>
  )
}
