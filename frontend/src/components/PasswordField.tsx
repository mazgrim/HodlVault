import { useState } from 'react'
import { Eye, EyeOff, Wand2 } from 'lucide-react'

interface Props {
  value: string
  onChange: (v: string) => void
  onGenerate?: () => void   // when set, shows a "genera password" button
  placeholder?: string
  autoFocus?: boolean
  required?: boolean
  defaultVisible?: boolean   // start with the password revealed (e.g. admin reset)
}

export default function PasswordField({
  value, onChange, onGenerate, placeholder, autoFocus, required, defaultVisible,
}: Props) {
  const [show, setShow] = useState(defaultVisible ?? false)
  const pad = onGenerate ? 'pr-16' : 'pr-10'

  return (
    <div className="relative">
      <input
        className={`input ${pad}`}
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        required={required}
      />
      <div className="absolute inset-y-0 right-2 flex items-center gap-0.5">
        {onGenerate && (
          <button
            type="button"
            tabIndex={-1}
            onClick={() => { onGenerate(); setShow(true) }}
            title="Genera password casuale"
            className="p-1 rounded text-gray-500 hover:text-gold-400 transition-colors"
          >
            <Wand2 size={16} />
          </button>
        )}
        <button
          type="button"
          tabIndex={-1}
          onClick={() => setShow((s) => !s)}
          title={show ? 'Nascondi password' : 'Mostra password'}
          className="p-1 rounded text-gray-500 hover:text-gold-400 transition-colors"
        >
          {show ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </div>
  )
}
