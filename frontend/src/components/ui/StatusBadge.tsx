import { clsx } from 'clsx'
import type { DocStatus } from '@/types'

const MAP: Record<DocStatus, { label: string; cls: string }> = {
  uploaded: { label: '待索引', cls: 'bg-slate-100 text-slate-500' },
  indexing:  { label: '索引中', cls: 'bg-yellow-100 text-warning' },
  indexed:   { label: '已索引', cls: 'bg-green-100 text-success' },
  failed:    { label: '失败',   cls: 'bg-red-100 text-danger' },
}

export default function StatusBadge({ status }: { status: DocStatus }) {
  const { label, cls } = MAP[status] ?? MAP.uploaded
  return (
    <span className={clsx('inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold', cls)}>
      {status === 'indexing' && (
        <span className="w-1.5 h-1.5 rounded-full bg-warning mr-1.5 animate-pulse" />
      )}
      {label}
    </span>
  )
}
