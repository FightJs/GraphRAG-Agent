import { useToastStore } from '@/hooks/useToast'
import { CheckCircle, AlertCircle, AlertTriangle, Info, X } from 'lucide-react'
import { clsx } from 'clsx'

const icons = { success: CheckCircle, error: AlertCircle, warning: AlertTriangle, info: Info }
const colors = {
  success: 'bg-green-50 border-green-200 text-green-800',
  error: 'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-yellow-50 border-yellow-200 text-yellow-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
}
const iconColors = { success: 'text-success', error: 'text-danger', warning: 'text-warning', info: 'text-primary' }

export default function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)
  const remove = useToastStore((s) => s.remove)

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => {
        const Icon = icons[t.type]
        return (
          <div
            key={t.id}
            className={clsx(
              'flex items-start gap-3 px-4 py-3 rounded-xl border shadow-lg min-w-[280px] max-w-sm pointer-events-auto animate-fade-in',
              colors[t.type]
            )}
          >
            <Icon size={16} className={clsx('mt-0.5 flex-shrink-0', iconColors[t.type])} />
            <p className="text-sm flex-1">{t.message}</p>
            <button onClick={() => remove(t.id)} className="opacity-50 hover:opacity-100 flex-shrink-0">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
