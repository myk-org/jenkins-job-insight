interface NavBadgeProps {
  count: number
  color: 'orange' | 'blue'
}

export function NavBadge({ count, color }: NavBadgeProps) {
  if (count <= 0) return null
  const bgClass = color === 'orange' ? 'bg-signal-orange' : 'bg-signal-blue'
  return (
    <span className={`absolute -top-1 -right-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full ${bgClass} px-1 text-[10px] font-bold text-white`}>
      {count > 99 ? '99+' : count}
    </span>
  )
}
