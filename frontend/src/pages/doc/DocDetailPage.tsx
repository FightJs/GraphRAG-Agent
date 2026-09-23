import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileText, Share2, MessageSquare, Play, Trash2, RefreshCw } from 'lucide-react'
import { docApi } from '@/services/api'
import StatusBadge from '@/components/ui/StatusBadge'
import { useToast } from '@/hooks/useToast'
import type { Document } from '@/types'

function fmtSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-border last:border-0">
      <span className="w-28 text-xs text-ts flex-shrink-0">{label}</span>
      <span className="text-sm text-tp break-all">{value ?? '-'}</span>
    </div>
  )
}

export default function DocDetailPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['docs', kbId],
    queryFn: () => docApi.list(kbId!),
    enabled: !!kbId,
  })
  const doc: Document | undefined = docs.find(d => d.doc_id === docId)

  const indexMut = useMutation({
    mutationFn: (id: string) => docApi.startIndex(id),
    onSuccess: (task) => {
      qc.invalidateQueries({ queryKey: ['docs', kbId] })
      navigate(`/kb/${kbId}/doc/${task.doc_id}/index/${task.task_id}`)
    },
    onError: () => toast.error('启动索引失败'),
  })

  const deleteMut = useMutation({
    mutationFn: docApi.delete,
    onSuccess: () => {
      toast.success('文档已删除')
      navigate(`/kb/${kbId}`)
    },
    onError: () => toast.error('删除失败'),
  })

  if (isLoading) return <div className="p-8 text-sm text-ts">加载中...</div>
  if (!doc) {
    return (
      <div className="p-8">
        <p className="text-sm text-ts mb-4">文档不存在或已删除</p>
        <button onClick={() => navigate(`/kb/${kbId}`)} className="text-sm text-primary">返回文档库</button>
      </div>
    )
  }

  const canIndex = doc.status === 'uploaded' || doc.status === 'failed'
  const canEnter = doc.status === 'indexed'

  return (
    <div className="h-full overflow-auto">
      <div className="h-[56px] bg-surface border-b border-border flex items-center justify-between px-7 flex-shrink-0">
        <nav className="flex items-center gap-1.5 text-sm">
          <button className="text-ts hover:text-tp flex items-center gap-1" onClick={() => navigate(`/kb/${kbId}`)}>
            <ArrowLeft size={14} /> 文档库
          </button>
          <span className="text-ts">/</span>
          <span className="font-semibold text-tp truncate max-w-[280px]">{doc.original_name}</span>
        </nav>
        <div className="flex items-center gap-2">
          {canIndex && (
            <button
              onClick={() => indexMut.mutate(doc.doc_id)}
              disabled={indexMut.isPending}
              className="flex items-center gap-1.5 h-8 px-3.5 bg-primary text-white rounded-lg text-xs font-semibold hover:bg-primary-hover disabled:opacity-60"
            >
              {doc.status === 'failed' ? <RefreshCw size={14} /> : <Play size={14} />}
              {doc.status === 'failed' ? '重新索引' : '开始索引'}
            </button>
          )}
          {canEnter && (
            <>
              <Link to={`/kb/${kbId}/doc/${doc.doc_id}/kg`}
                className="flex items-center gap-1.5 h-8 px-3.5 border border-border text-tp rounded-lg text-xs font-semibold hover:bg-bg">
                <Share2 size={14} /> 知识图谱
              </Link>
              <Link to={`/kb/${kbId}/doc/${doc.doc_id}/qa`}
                className="flex items-center gap-1.5 h-8 px-3.5 border border-border text-tp rounded-lg text-xs font-semibold hover:bg-bg">
                <MessageSquare size={14} /> 问答
              </Link>
            </>
          )}
          <button
            onClick={() => { if (window.confirm(`确认删除「${doc.original_name}」？`)) deleteMut.mutate(doc.doc_id) }}
            disabled={deleteMut.isPending}
            className="flex items-center gap-1.5 h-8 px-3.5 border border-danger/40 text-danger rounded-lg text-xs font-semibold hover:bg-danger/5 disabled:opacity-60"
          >
            <Trash2 size={14} /> 删除
          </button>
        </div>
      </div>

      <div className="p-7 max-w-3xl">
        <div className="flex items-start gap-4 mb-8">
          <div className="w-14 h-14 rounded-xl bg-bg border border-border flex items-center justify-center flex-shrink-0">
            <FileText size={24} className="text-primary" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold text-tp mb-1 truncate">{doc.original_name}</h1>
            <div className="flex items-center gap-3 text-xs text-ts">
              <StatusBadge status={doc.status} />
              <span>{doc.file_format}</span>
              <span>{fmtSize(doc.file_size)}</span>
            </div>
          </div>
        </div>

        {doc.error_message && (
          <div className="mb-6 px-4 py-3 bg-danger/5 border border-danger/30 rounded-xl text-sm text-danger">
            {doc.error_message}
          </div>
        )}

        <div className="bg-surface border border-border rounded-2xl px-5 py-2 mb-6">
          <Row label="文档 ID" value={<span className="font-mono text-xs">{doc.doc_id}</span>} />
          <Row label="状态" value={<StatusBadge status={doc.status} />} />
          <Row label="格式" value={doc.file_format} />
          <Row label="大小" value={fmtSize(doc.file_size)} />
          <Row label="页数" value={doc.page_count ?? '-'} />
          <Row label="实体数" value={doc.node_count ?? '-'} />
          <Row label="关系数" value={doc.edge_count ?? '-'} />
          <Row label="创建时间" value={doc.created_at ? doc.created_at.slice(0, 19).replace('T', ' ') : '-'} />
          <Row label="更新时间" value={doc.updated_at ? doc.updated_at.slice(0, 19).replace('T', ' ') : '-'} />
        </div>

        {doc.status === 'indexed' && (
          <p className="text-xs text-ts">
            该文档已索引。可进入知识图谱查看实体关系，或在问答页使用 KG-Only / 混合 / 语义检索提问；
            含表格与图片的片段会在问答上下文中自动展开为摘要。
          </p>
        )}
      </div>
    </div>
  )
}
