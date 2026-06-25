export default function Spinner({ size = 6 }: { size?: number }) {
  return (
    <div
      className={`w-${size} h-${size} rounded-full border-2 border-gray-600 border-t-gold-500 animate-spin`}
      role="status"
    />
  )
}

export function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <Spinner size={8} />
    </div>
  )
}
