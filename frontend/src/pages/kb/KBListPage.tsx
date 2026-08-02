import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Database, FileText, BarChart2, Search, MoreHorizontal, Trash2, Pencil, ArrowRight } from 'lucide-react'
import { kbApi } from '@/services/api'
import type { KnowledgeBase } from '@/types'
import Modal from '@/components/ui/Modal'
import EmptyState from '@/components/ui/EmptyState'
import { useToast } from '@/hooks/useToast'
import { clsx } from 'clsx'

const KB_COLORS = ['#3B82F6', '#8B5CF6', '#16A34A', '#F97316', '#EC4899', '#06B6D4']

function KBCard({ kb, onDelete }: { kb: KnowledgeBase; onDelete: (id: string) => void }) {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="bg-surface border border-border rounded-xl p-6 hover:shadow-md transition-shadow flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: kb.color + '20' }}>
          <Database size={22} style={{ color: kb.color }} />
        </div>
        <div className="relative">
          <button onClick={() => setMenuOpen(!menuOpen)} className="text-ts hover:text-tp p-1 rounded">
            <MoreHorizontal size={18} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-36 bg-surface border border-border rounded-xl shadow-lg py-1 z-10">
              <button className="w-full flex items-center gap-2 px-3 py-2 text-sm text-tp hover:bg-bg">
                <Pencil size={13} className="text-ts" /> 编辑
              </button>
              <button
                onClick={() => { onDelete(kb.kb_id); setMenuOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-danger hover:bg-red-50"
              >
                <Trash2 size={13} /> 删除
              </button>
            </div>
          )}
        </div>
      </div>

      <div>
        <h3 className="font-semibold text-tp text-base mb-1">{kb.name}</h3>
        <p className="text-xs text-ts line-clamp-2">{kb.description || '暂无描述'}</p>
      </div>

      <div className="flex items-center gap-4">
        {[
          { icon: FileText, val: `${kb.doc_count} 份`, tip: '文档' },
          { icon: Database, val: `${kb.indexed_count} 已索引`, tip: '' },
          { icon: BarChart2, val: `${kb.total_nodes} 节点`, tip: '知识节点' },
        ].map(({ icon: Icon, val }) => (
          <div key={val} className="flex items-center gap-1 text-xs text-ts">
            <Icon size={12} /> {val}
          </div>
        ))}
      </div>

      <button
        onClick={() => navigate(`/kb/${kb.kb_id}`)}
        className="w-full flex items-center justify-center gap-1.5 h-9 bg-primary/10 hover:bg-primary/20 text-primary text-sm font-semibold rounded-lg transition-colors"
      >
        进入知识库 <ArrowRight size={14} />
      </button>
    </div>
  )
}

export default function KBListPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', color: KB_COLORS[0] })

  const { data: kbs = [], isLoading } = useQuery({ queryKey: ['kbs'], queryFn: kbApi.list })

  const createMut = useMutation({
    mutationFn: kbApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kbs'] }); setShowCreate(false); setForm({ name: '', description: '', color: KB_COLORS[0] }); toast.success('知识库创建成功') },
    onError: () => toast.error('创建失败，请重试'),
  })

  const deleteMut = useMutation({
    mutationFn: kbApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['kbs'] }); toast.success('知识库已删除') },
  })

  const filtered = kbs.filter((k) => k.name.toLowerCase().includes(search.toLowerCase()))

  const stats = [
    { label: '总知识库', val: kbs.length },
    { label: '总文档数', val: kbs.reduce((s, k) => s + k.doc_count, 0) },
    { label: '已索引', val: kbs.reduce((s, k) => s + k.indexed_count, 0) },
    { label: '累计节点', val: kbs.reduce((s, k) => s + k.total_nodes, 0) },
  ]

  return (
    <div className="h-full flex flex-col">
      {/* Stats banner */}
      <div className="bg-primary/5 border-b border-border px-8 py-3 flex items-center gap-8">
        {stats.map(({ label, val }) => (
          <div key={label} className="flex items-center gap-2">
            <span className="text-lg font-bold text-primary">{val}</span>
            <span className="text-xs text-ts">{label}</span>
          </div>
        ))}
      </div>

      {/* Header */}
      <div className="flex items-center justify-between px-8 pt-7 pb-5">
        <h1 className="text-2xl font-bold text-tp">我的知识库</h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 h-9 px-3 bg-surface border border-border rounded-lg w-56">
            <Search size={14} className="text-ts" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索知识库..."
              className="flex-1 text-sm outline-none bg-transparent"
            />
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 h-9 px-4 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover transition-colors"
          >
            <Plus size={15} /> 新建知识库
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-auto px-8 pb-8">
        {isLoading ? (
          <div className="grid grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-52 rounded-xl skeleton" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Database size={32} />}
            title="暂无知识库"
            description="创建您的第一个知识库，开始智能问答"
            action={
              <button onClick={() => setShowCreate(true)} className="h-9 px-5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover transition-colors">
                创建第一个知识库
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {filtered.map((kb) => (
              <KBCard key={kb.kb_id} kb={kb} onDelete={(id) => deleteMut.mutate(id)} />
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      <Modal
        open={showCreate} onClose={() => setShowCreate(false)} title="新建知识库"
        footer={
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowCreate(false)} className="h-9 px-4 border border-border rounded-lg text-sm text-ts hover:bg-bg">取消</button>
            <button
              onClick={() => createMut.mutate(form)}
              disabled={!form.name || createMut.isPending}
              className="h-9 px-4 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover disabled:opacity-50"
            >
              {createMut.isPending ? '创建中...' : '创建'}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-tp mb-1.5">知识库名称 *</label>
            <input
              value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例如：HR 简历库"
              className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-tp mb-1.5">描述</label>
            <textarea
              value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="简短描述该知识库的用途..."
              rows={3}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:border-primary resize-none"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-tp mb-2">图标颜色</label>
            <div className="flex gap-2">
              {KB_COLORS.map((c) => (
                <button
                  key={c} onClick={() => setForm({ ...form, color: c })}
                  className={clsx('w-8 h-8 rounded-full transition-all', form.color === c && 'ring-2 ring-offset-2 ring-gray-400')}
                  style={{ background: c }}
                />
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}
