import type { ReactNode } from 'react'

interface Props {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export default function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-bg flex items-center justify-center mb-4 text-ts">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-tp mb-1">{title}</h3>
      {description && <p className="text-sm text-ts max-w-xs mb-6">{description}</p>}
      {action}
    </div>
  )
}
