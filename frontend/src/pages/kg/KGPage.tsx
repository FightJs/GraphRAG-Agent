import { useRef, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ZoomIn, ZoomOut, Maximize2, Pencil, X, MapPin } from 'lucide-react'
import { kgApi } from '@/services/api'
import type { KGNode } from '@/types'
import { clsx } from 'clsx'
import {
  NODE_COLOR,
  NODE_LABEL,
  renderKGGraph,
  type RenderKGHandle,
} from '@/components/kg/kgTheme'

export default function KGPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)
  const graphRef = useRef<RenderKGHandle | null>(null)
  const [selected, setSelected] = useState<KGNode | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('ALL')
  const [layoutMode, setLayoutMode] = useState<'force' | 'hierarchy'>('force')

  const { data: kg, isLoading } = useQuery({
    queryKey: ['kg', docId],
    queryFn: () => kgApi.get(docId!),
    enabled: !!docId,
  })

  // 仅在数据/筛选/布局变化时重建模拟；选中态用 setSelectedId 原地高亮，避免点击后整图散开
  useEffect(() => {
    if (!kg || !svgRef.current) return

    const filteredNodes = typeFilter === 'ALL'
      ? kg.nodes
      : kg.nodes.filter(n => n.type === typeFilter)
    const nodeIds = new Set(filteredNodes.map(n => n.id))
    const filteredEdges = kg.edges.filter(
      e => nodeIds.has(String(e.source)) && nodeIds.has(String(e.target)),
    )

    const handle = renderKGGraph({
      svg: svgRef.current,
      nodes: filteredNodes,
      edges: filteredEdges,
      layoutMode,
      selectedId: null,
      onSelect: setSelected,
      markerId: 'kg-arrow',
    })
    graphRef.current = handle

    if (layoutMode === 'force') {
      const t = window.setTimeout(() => handle.fit(), 700)
      return () => {
        window.clearTimeout(t)
        handle.stop()
      }
    }
    return () => handle.stop()
  }, [kg, typeFilter, layoutMode])

  useEffect(() => {
    graphRef.current?.setSelectedId(selected?.id ?? null)
  }, [selected?.id])

  const types = kg ? ['ALL', ...Array.from(new Set(kg.nodes.map(n => n.type)))] : ['ALL']

  return (
    <div className="h-full flex flex-col">
      <div className="h-[56px] bg-surface border-b border-border flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-sm text-tp">知识图谱</span>
          {kg && (
            <span className="text-xs bg-primary/10 text-primary px-2.5 py-0.5 rounded-full font-semibold">
              {kg.meta.total_nodes} 节点 · {kg.meta.total_edges} 关系
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 h-8 px-1.5 bg-bg border border-border rounded-lg">
            {(['force', 'hierarchy'] as const).map(mode => (
              <button
                key={mode}
                onClick={() => setLayoutMode(mode)}
                className={clsx(
                  'px-2.5 py-1.5 rounded text-xs font-medium transition-colors',
                  layoutMode === mode ? 'bg-primary text-white' : 'text-ts hover:text-tp',
                )}
              >
                {mode === 'force' ? '力引导' : '分层'}
              </button>
            ))}
          </div>
          <button
            onClick={() => graphRef.current?.zoomIn()}
            title="放大"
            className="w-8 h-8 border border-border rounded-lg flex items-center justify-center text-ts hover:bg-bg hover:text-tp transition-colors"
          >
            <ZoomIn size={14} />
          </button>
          <button
            onClick={() => graphRef.current?.zoomOut()}
            title="缩小"
            className="w-8 h-8 border border-border rounded-lg flex items-center justify-center text-ts hover:bg-bg hover:text-tp transition-colors"
          >
            <ZoomOut size={14} />
          </button>
          <button
            onClick={() => graphRef.current?.fit()}
            title="适应画布"
            className="w-8 h-8 border border-border rounded-lg flex items-center justify-center text-ts hover:bg-bg hover:text-tp transition-colors"
          >
            <Maximize2 size={14} />
          </button>
          <button
            onClick={() => navigate(`/kb/${kbId}/doc/${docId}/kg/edit`)}
            className="flex items-center gap-1.5 h-8 px-3.5 bg-warning text-white rounded-lg text-xs font-semibold hover:opacity-90"
          >
            <Pencil size={13} /> 进入编辑模式
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 relative bg-gradient-to-br from-slate-50 via-blue-50/40 to-indigo-50/30">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
                <div className="text-ts text-sm">加载知识图谱...</div>
              </div>
            </div>
          )}
          <svg ref={svgRef} className="w-full h-full block" />

          <div className="absolute bottom-4 left-4 flex flex-wrap gap-1.5 max-w-[70%]">
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={clsx(
                  'flex items-center gap-1 h-6 px-2.5 rounded-full text-[10px] font-semibold transition-all shadow-sm',
                  typeFilter === t
                    ? 'bg-tp text-white'
                    : 'bg-white/90 backdrop-blur border border-border text-ts hover:bg-white hover:text-tp',
                )}
              >
                {t !== 'ALL' && (
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ background: NODE_COLOR[t] ?? '#94A3B8' }}
                  />
                )}
                {t === 'ALL' ? '全部' : NODE_LABEL[t] ?? t}
              </button>
            ))}
          </div>

          <div className="absolute bottom-4 right-4 text-[10px] text-ts/80 bg-white/70 backdrop-blur px-2 py-1 rounded-md border border-border/60 pointer-events-none">
            拖拽节点 · 滚轮缩放 · 点击查看详情
          </div>

          {/* 浮层详情：不挤压画布宽度，选中时视角不跳 */}
          {selected && (
            <div className="absolute right-0 top-0 bottom-0 w-72 bg-surface border-l border-border shadow-xl flex flex-col z-10">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ background: NODE_COLOR[selected.type] ?? '#94A3B8' }}
                  />
                  <span className="font-semibold text-sm text-tp truncate">{selected.label}</span>
                </div>
                <button
                  onClick={() => setSelected(null)}
                  className="text-ts hover:text-tp flex-shrink-0"
                >
                  <X size={15} />
                </button>
              </div>
              <div className="p-4 flex-1 space-y-3 text-xs overflow-y-auto">
                <div className="flex items-center gap-2">
                  <span className="text-ts w-14 flex-shrink-0">类型</span>
                  <span
                    className="px-2 py-0.5 rounded-full font-semibold"
                    style={{
                      background: (NODE_COLOR[selected.type] ?? '#94A3B8') + '20',
                      color: NODE_COLOR[selected.type] ?? '#94A3B8',
                    }}
                  >
                    {NODE_LABEL[selected.type] ?? selected.type}
                  </span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="text-ts w-14 flex-shrink-0">属性</span>
                  <pre className="bg-slate-900 text-slate-300 rounded-lg p-3 text-[10px] font-mono flex-1 overflow-auto leading-relaxed">
                    {JSON.stringify(selected.attributes, null, 2)}
                  </pre>
                </div>
              </div>
              <div className="p-4 border-t border-border">
                <button className="w-full flex items-center justify-center gap-1.5 h-8 border border-border rounded-lg text-xs text-ts hover:bg-bg transition-colors">
                  <MapPin size={12} /> 在文档中定位
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
