import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, FolderUp, Search, Share2, MessageSquare, MoreHorizontal, Trash2, RefreshCw, Play, FileText } from 'lucide-react'
import { docApi } from '@/services/api'
import type { Document, DocStatus } from '@/types'
import StatusBadge from '@/components/ui/StatusBadge'
import EmptyState from '@/components/ui/EmptyState'
import { useToast } from '@/hooks/useToast'
import { clsx } from 'clsx'
const STATUS_FILTERS: { label: string; value: DocStatus | 'all' }[] = [
  { label: '全部', value: 'all' },
  { label: '已索引', value: 'indexed' },
  { label: '索引中', value: 'indexing' },
  { label: '待索引', value: 'uploaded' },
  { label: '失败', value: 'failed' },
]

const FMT_COLOR: Record<string, string> = {
  PDF: '#EF4444', DOCX: '#3B82F6', XLSX: '#16A34A', PPTX: '#F97316',
  MD: '#8B5CF6', TXT: '#64748B', HTML: '#06B6D4',
}

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function DocLibPage() {
  const { kbId } = useParams<{ kbId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const batchInputRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<DocStatus | 'all'>('all')
  const [uploading, setUploading] = useState(false)
  const [batchUploading, setBatchUploading] = useState(false)

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['docs', kbId],
    queryFn: () => docApi.list(kbId!),
    enabled: !!kbId,
    refetchInterval: (q) => q.state.data?.some((d) => d.status === 'indexing') ? 3000 : false,
  })

  const indexMut = useMutation({
    mutationFn: (docId: string) => docApi.startIndex(docId),
    onSuccess: (task) => {
      qc.invalidateQueries({ queryKey: ['docs', kbId] })
      navigate(`/kb/${kbId}/doc/${task.doc_id}/index/${task.task_id}`)
    },
    onError: () => toast.error('启动索引失败'),
  })

  const deleteMut = useMutation({
    mutationFn: docApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['docs', kbId] }); toast.success('文档已删除') },
  })

  const batchIndexMut = useMutation({
    mutationFn: (docIds: string[]) => docApi.batchIndex(docIds),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['docs', kbId] })
      const ok = result.tasks.length
      const skipped = result.skipped.length
      if (ok && skipped) toast.warning(`已启动 ${ok} 个索引任务，跳过 ${skipped} 个`)
      else if (ok) toast.success(`已启动 ${ok} 个索引任务`)
      else toast.warning('没有可启动的文档（可能正在索引中）')
    },
    onError: () => toast.error('批量启动索引失败'),
  })

  const handleUpload = async (files: FileList | null) => {
    if (!files || !kbId) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        await docApi.upload(kbId, file)
      }
      qc.invalidateQueries({ queryKey: ['docs', kbId] })
      toast.success(`${files.length} 份文档上传成功`)
    } catch {
      toast.error('上传失败，请重试')
    } finally {
      setUploading(false)
    }
  }

  const handleBatchUpload = async (files: FileList | null) => {
    if (!files || !kbId || files.length === 0) return
    setBatchUploading(true)
    try {
      const result = await docApi.batchUpload(kbId, Array.from(files))
      qc.invalidateQueries({ queryKey: ['docs', kbId] })
      const failCount = result.failed.length
      if (failCount > 0) {
        toast.warning(`${result.uploaded.length} 份上传成功，${failCount} 份失败`)
      } else {
        toast.success(`批量上传成功：${result.uploaded.length} 份文档`)
      }
    } catch {
      toast.error('批量上传失败，请重试')
    } finally {
      setBatchUploading(false)
      if (batchInputRef.current) batchInputRef.current.value = ''
    }
  }

  const filtered = docs
    .filter((d) => statusFilter === 'all' || d.status === statusFilter)
    .filter((d) => d.original_name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="h-[56px] bg-surface border-b border-border flex items-center justify-between px-7 flex-shrink-0">
        <nav className="flex items-center gap-1.5 text-sm">
          <span className="text-ts cursor-pointer hover:text-tp" onClick={() => navigate('/')}>我的知识库</span>
          <span className="text-ts">/</span>
          <span className="font-semibold text-tp">文档库</span>
        </nav>
        <div className="flex items-center gap-2">
          <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(e) => handleUpload(e.target.files)} accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.html" />
          <input ref={batchInputRef} type="file" multiple className="hidden" onChange={(e) => handleBatchUpload(e.target.files)} accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.html" />
          <button
            onClick={() => fileInputRef.current?.click()} disabled={uploading || batchUploading}
            className="flex items-center gap-1.5 h-8 px-3.5 bg-primary text-white rounded-lg text-xs font-semibold hover:bg-primary-hover disabled:opacity-60"
          >
            <Upload size={14} />{uploading ? '上传中...' : '上传文档'}
          </button>
          <button
            onClick={() => batchInputRef.current?.click()} disabled={uploading || batchUploading}
            className="flex items-center gap-1.5 h-8 px-3.5 border border-border bg-surface rounded-lg text-xs text-ts hover:bg-bg disabled:opacity-60"
          >
            <FolderUp size={14} />{batchUploading ? '批量上传中...' : '批量导入'}
          </button>
          <button
            onClick={() => {
              const ids = docs.filter(d => d.status === 'uploaded' || d.status === 'failed').map(d => d.doc_id).slice(0, 10)
              if (!ids.length) { toast.warning('没有待索引的文档'); return }
              batchIndexMut.mutate(ids)
            }}
            disabled={batchIndexMut.isPending || uploading || batchUploading}
            className="flex items-center gap-1.5 h-8 px-3.5 border border-border text-tp rounded-lg text-xs font-semibold hover:bg-bg disabled:opacity-60"
          >
            <Play size={14} />{batchIndexMut.isPending ? '启动中...' : '批量索引'}
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center justify-between px-7 py-3 bg-bg border-b border-border">
        <div className="flex items-center gap-2 h-8 px-3 bg-surface border border-border rounded-lg w-64">
          <Search size={13} className="text-ts" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索文档..." className="flex-1 text-xs outline-none bg-transparent" />
        </div>
        <div className="flex items-center gap-1.5">
          {STATUS_FILTERS.map(({ label, value }) => (
            <button
              key={value} onClick={() => setStatusFilter(value)}
              className={clsx(
                'h-7 px-3 rounded-full text-xs font-medium transition-colors',
                statusFilter === value ? 'bg-primary text-white' : 'bg-surface border border-border text-ts hover:bg-bg'
              )}
            >{label}</button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-7 py-4">
        {isLoading ? (
          <div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-14 rounded-lg skeleton" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="暂无文档"
            description="上传 PDF、Word、Excel 等格式的文档开始索引"
            action={
              <button onClick={() => fileInputRef.current?.click()} className="h-9 px-5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover">
                上传第一份文档
              </button>
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-ts font-semibold">
                <th className="text-left py-2 px-4 w-[36%]">文档名称</th>
                <th className="text-left py-2 px-3 w-[80px]">格式</th>
                <th className="text-left py-2 px-3 w-[110px]">状态</th>
                <th className="text-left py-2 px-3 w-[80px]">节点数</th>
                <th className="text-left py-2 px-3 w-[80px]">大小</th>
                <th className="text-left py-2 px-3 w-[110px]">上传时间</th>
                <th className="text-left py-2 px-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((doc) => (
                <DocRow
                  key={doc.doc_id}
                  doc={doc}
                  kbId={kbId!}
                  onIndex={() => indexMut.mutate(doc.doc_id)}
                  onDelete={() => deleteMut.mutate(doc.doc_id)}
                  onKG={() => navigate(`/kb/${kbId}/doc/${doc.doc_id}/kg`)}
                  onQA={() => navigate(`/kb/${kbId}/doc/${doc.doc_id}/qa`)}
                  onDetail={() => navigate(`/kb/${kbId}/doc/${doc.doc_id}`)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function DocRow({ doc, kbId, onIndex, onDelete, onKG, onQA, onDetail }: { doc: Document; kbId: string; onIndex: () => void; onDelete: () => void; onKG: () => void; onQA: () => void; onDetail: () => void }) {
  const [menu, setMenu] = useState(false)
  const fmt = doc.file_format.toUpperCase()
  const color = FMT_COLOR[fmt] ?? '#94A3B8'
  const canAct = doc.status === 'indexed'
  const canIndex = doc.status === 'uploaded' || doc.status === 'failed'

  return (
    <tr className="border-b border-border hover:bg-bg/50 group">
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-9 h-5 rounded text-[10px] font-bold" style={{ background: color + '20', color }}>{fmt}</span>
          <button type="button" onClick={onDetail}
            className="text-tp font-medium truncate max-w-xs hover:text-primary text-left" title="查看详情">{doc.original_name}</button>
        </div>
      </td>
      <td className="py-3 px-3 text-ts">{fmt}</td>
      <td className="py-3 px-3"><StatusBadge status={doc.status} /></td>
      <td className="py-3 px-3 text-ts">{doc.node_count || '—'}</td>
      <td className="py-3 px-3 text-ts">{fmtSize(doc.file_size)}</td>
      <td className="py-3 px-3 text-ts text-xs">{doc.created_at?.slice(0, 10)}</td>
      <td className="py-3 px-3">
        <div className="flex items-center gap-2">
          {canIndex && (
            <button onClick={onIndex} className="text-primary hover:text-primary-hover" title={doc.status === 'failed' ? '重试索引' : '开始索引'}>
              {doc.status === 'failed' ? <RefreshCw size={15} /> : <Play size={15} />}
            </button>
          )}
          {canAct && (
            <>
              <button onClick={onKG} className="text-ts hover:text-primary" title="查看知识图谱"><Share2 size={15} /></button>
              <button onClick={onQA} className="text-ts hover:text-primary" title="开始问答"><MessageSquare size={15} /></button>
            </>
          )}
          <div className="relative">
            <button onClick={() => setMenu(!menu)} className="text-ts hover:text-tp"><MoreHorizontal size={15} /></button>
            {menu && (
              <div className="absolute right-0 top-full mt-1 w-32 bg-surface border border-border rounded-xl shadow-lg py-1 z-10">
                <button onClick={() => { onDelete(); setMenu(false) }} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-danger hover:bg-red-50">
                  <Trash2 size={12} /> 删除文档
                </button>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  )
}
