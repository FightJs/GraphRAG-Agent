import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Share2, FileText } from 'lucide-react'
import { docApi } from '@/services/api'
import EmptyState from '@/components/ui/EmptyState'

const FMT_COLOR: Record<string, string> = {
  PDF: '#EF4444', DOCX: '#3B82F6', XLSX: '#16A34A', PPTX: '#F97316',
  MD: '#8B5CF6', TXT: '#64748B', HTML: '#06B6D4',
}

export default function KGEntryPage() {
  const { kbId } = useParams<{ kbId: string }>()
  const navigate = useNavigate()

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['docs', kbId],
    queryFn: () => docApi.list(kbId!),
    enabled: !!kbId,
  })

  const indexedDocs = docs.filter((d) => d.status === 'indexed')

  return (
    <div className="h-full flex flex-col">
      <div className="h-[56px] bg-surface border-b border-border flex items-center px-7 flex-shrink-0">
        <span className="font-semibold text-sm text-tp">知识图谱</span>
        <span className="text-xs text-ts ml-3">选择一份已索引的文档查看其知识图谱</span>
      </div>

      <div className="flex-1 overflow-auto px-7 py-5">
        {isLoading ? (
          <div className="grid grid-cols-3 gap-3">
            {[...Array(6)].map((_, i) => <div key={i} className="h-24 rounded-xl skeleton" />)}
          </div>
        ) : indexedDocs.length === 0 ? (
          <EmptyState
            icon={<Share2 size={28} />}
            title="暂无可查看的知识图谱"
            description="请先在文档库中上传并索引文档，索引完成后即可在此查看知识图谱"
            action={
              <button
                onClick={() => navigate(`/kb/${kbId}`)}
                className="h-9 px-5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover"
              >
                前往文档库
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {indexedDocs.map((doc) => {
              const fmt = doc.file_format.toUpperCase()
              const color = FMT_COLOR[fmt] ?? '#94A3B8'
              return (
                <button
                  key={doc.doc_id}
                  onClick={() => navigate(`/kb/${kbId}/doc/${doc.doc_id}/kg`)}
                  className="flex items-start gap-3 p-4 bg-surface border border-border rounded-xl text-left hover:border-primary hover:shadow-sm transition-all"
                >
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: color + '20' }}>
                    <FileText size={16} style={{ color }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-tp truncate">{doc.original_name}</p>
                    <p className="text-xs text-ts mt-1">{doc.node_count} 节点 · {doc.edge_count} 关系</p>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
