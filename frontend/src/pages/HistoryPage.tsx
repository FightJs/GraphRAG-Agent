import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { History, ThumbsUp, ThumbsDown, ChevronDown, ChevronUp, Search, Zap } from 'lucide-react'
import { qaApi } from '@/services/api'
import type { QAHistory } from '@/types'
import EmptyState from '@/components/ui/EmptyState'

function HistoryItem({ item }: { item: QAHistory }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-start gap-4 px-5 py-4 hover:bg-bg text-left transition-colors">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-tp mb-1 truncate">{item.question}</p>
          <div className="flex items-center gap-3 text-xs text-ts">
            <span>{item.created_at?.slice(0, 16).replace('T', ' ')}</span>
            <span className="bg-primary/10 text-primary px-2 py-0.5 rounded-full font-medium">
              {item.retrieval_mode === 'kg_only' ? 'KG-Only' : item.retrieval_mode === 'agentic' ? 'RRF Agentic' : 'Auto'}
            </span>
            <span className="flex items-center gap-0.5"><Zap size={10} />{(item.input_tokens ?? 0) + (item.output_tokens ?? 0)} tokens</span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {open ? <ChevronUp size={15} className="text-ts" /> : <ChevronDown size={15} className="text-ts" />}
        </div>
      </button>
      {open && (
        <div className="border-t border-border px-5 py-4 bg-bg/50">
          <p className="text-sm text-tp leading-relaxed whitespace-pre-wrap">{item.answer}</p>
        </div>
      )}
    </div>
  )
}

export default function HistoryPage() {
  const [search, setSearch] = useState('')
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['qa-history'],
    queryFn: () => qaApi.history(),
  })

  const filtered = history.filter(h =>
    h.question.toLowerCase().includes(search.toLowerCase()) ||
    h.answer.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-8 pt-7 pb-5">
        <h1 className="text-2xl font-bold text-tp">问答历史</h1>
        <div className="flex items-center gap-2 h-9 px-3 bg-surface border border-border rounded-lg w-64">
          <Search size={14} className="text-ts" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索历史问答..."
            className="flex-1 text-sm outline-none bg-transparent" />
        </div>
      </div>

      <div className="flex-1 overflow-auto px-8 pb-8">
        {isLoading ? (
          <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="h-20 rounded-xl skeleton" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={<History size={28} />} title="暂无问答历史" description="开始您的第一次智能问答" />
        ) : (
          <div className="space-y-3">
            {filtered.map(item => <HistoryItem key={item.query_id} item={item} />)}
          </div>
        )}
      </div>
    </div>
  )
}
