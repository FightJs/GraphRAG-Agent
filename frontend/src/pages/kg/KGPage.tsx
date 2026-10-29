import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Maximize2, Pencil, Search, X, ZoomIn, ZoomOut } from 'lucide-react'
import { clsx } from 'clsx'
import { kgApi } from '@/services/api'
import type { KGNode } from '@/types'
import { buildGraphIndex, buildVisibleGraph, type ViewMode } from '@/components/kg/graphModel'
import { NODE_COLOR, NODE_LABEL, renderKGGraph, type RenderKGHandle } from '@/components/kg/kgTheme'

const button = 'h-8 px-3 border border-border rounded-lg text-xs font-medium hover:bg-bg disabled:opacity-40'
const viewNames: Record<ViewMode, string> = { overview: '主干概览', focus: '局部探索', all: '完整图谱' }

export default function KGPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)
  const graphRef = useRef<RenderKGHandle | null>(null)
  const positions = useRef(new Map<string, { x: number; y: number }>())
  const viewport = useRef<{ x: number; y: number; k: number } | undefined>()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [mode, setMode] = useState<ViewMode>('overview')
  const [expanded, setExpanded] = useState(new Map<string, number>())
  const [pinned, setPinned] = useState(new Set<string>())
  const [revealed, setRevealed] = useState(new Set<string>())
  const [neighborExpanded, setNeighborExpanded] = useState(new Map<string, Set<string>>())
  const [types, setTypes] = useState(new Set<string>())
  const [keepContext, setKeepContext] = useState(true)
  const [search, setSearch] = useState('')
  const [showList, setShowList] = useState(false)
  const [layoutMode, setLayoutMode] = useState<'force' | 'hierarchy'>('force')
  const { data: kg, isLoading, isError, refetch } = useQuery({ queryKey: ['kg', docId], queryFn: () => kgApi.get(docId!), enabled: !!docId })
  const index = useMemo(() => kg ? buildGraphIndex(kg) : null, [kg])
  const visible = useMemo(() => {
    if (!kg || !index) return null
    const combined = new Set(revealed)
    neighborExpanded.forEach(ids => ids.forEach(id => combined.add(id)))
    return buildVisibleGraph(kg, index, { mode, selectedId, expanded, pinned, revealed: combined, types, keepContext })
  }, [kg, index, mode, selectedId, expanded, pinned, revealed, neighborExpanded, types, keepContext])
  const selected = selectedId ? index?.nodes.get(selectedId) ?? null : null

  useEffect(() => {
    positions.current.clear(); viewport.current = undefined
    setSelectedId(null); setMode('overview'); setExpanded(new Map()); setPinned(new Set()); setRevealed(new Set()); setNeighborExpanded(new Map()); setTypes(new Set()); setSearch(''); setShowList(false); setLayoutMode('force')
  }, [docId])
  const expandGroup = useCallback((id: string) => setExpanded(prev => {
    const next = new Map(prev); next.set(id, (next.get(id) ?? 0) + 12); return next
  }), [])
  const handleSelect = useCallback((node: KGNode | null) => {
    if (node?.type === '__GROUP__') { expandGroup(node.id); return }
    setSelectedId(node?.id ?? null)
    if (!node) setMode(current => current === 'focus' ? 'overview' : current)
  }, [expandGroup])
  useEffect(() => {
    if (!visible || !index || !svgRef.current) return
    const needsFit = !viewport.current
    const handle = renderKGGraph({ svg: svgRef.current, nodes: visible.nodes, edges: visible.edges, layoutMode, selectedId, onSelect: handleSelect, markerId: 'kg-arrow', degrees: index.degree, positions: positions.current, viewport: viewport.current, onViewport: v => { viewport.current = v } })
    graphRef.current = handle
    const t = needsFit ? window.setTimeout(() => handle.fit(), 600) : undefined
    return () => { if (t) window.clearTimeout(t); handle.stop() }
  }, [visible, index, layoutMode, handleSelect])
  useEffect(() => { graphRef.current?.setSelectedId(selectedId) }, [selectedId])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setSearch(''); setShowList(false); setSelectedId(null); setMode(current => current === 'focus' ? 'overview' : current) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const searchResults = useMemo(() => {
    if (!kg || !search.trim()) return []
    const q = search.trim().toLocaleLowerCase()
    return kg.nodes.filter(n => n.label.toLocaleLowerCase().includes(q)).slice(0, 30)
  }, [kg, search])
  const selectNode = (id: string) => { setRevealed(prev => new Set(prev).add(id)); setSelectedId(id); setSearch(''); setShowList(false) }
  const clearOverview = () => { setMode('overview'); setSelectedId(null); setExpanded(new Map()); setRevealed(new Set()); setNeighborExpanded(new Map()); setTypes(new Set()); setSearch(''); setShowList(false); positions.current.clear(); viewport.current = undefined }
  const toggleType = (type: string) => setTypes(prev => { const next = new Set(prev); next.has(type) ? next.delete(type) : next.add(type); return next })
  const togglePin = (id: string) => setPinned(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })
  const relatedGroups = index?.groups.filter(g => g.source === selectedId) ?? []
  const relatedEdges = kg?.edges.filter(e => e.source === selectedId || e.target === selectedId) ?? []
  const graphTypes = kg ? Array.from(new Set(kg.nodes.map(n => n.type))) : []
  const hiddenCount = visible?.hiddenCount ?? 0

  return <div className="h-full flex flex-col min-w-0">
    <div className="min-h-[56px] bg-surface border-b border-border flex flex-wrap items-center justify-between gap-2 px-4 py-2 flex-shrink-0">
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-sm text-tp">知识图谱</span>{kg && visible && <span className="text-xs text-ts">显示 {visible.realCount} / {kg.nodes.length} 个实体 · {visible.groups.length} 个折叠组 · 共 {kg.edges.length} 条关系</span>}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        <button onClick={() => graphRef.current?.zoomIn()} title="放大" aria-label="放大" className={button}><ZoomIn size={15} /></button>
        <button onClick={() => graphRef.current?.zoomOut()} title="缩小" aria-label="缩小" className={button}><ZoomOut size={15} /></button>
        <button onClick={() => graphRef.current?.fit()} title="适应画布" aria-label="适应画布" className={button}><Maximize2 size={15} /></button>
        <button onClick={() => navigate(`/kb/${kbId}/doc/${docId}/kg/edit`)} className="h-8 px-3 flex items-center gap-1.5 bg-warning text-white rounded-lg text-xs font-semibold"><Pencil size={13} /> 编辑图谱</button>
      </div>
    </div>
    <div className="px-4 py-2 border-b border-border bg-white flex items-center flex-wrap gap-2">
      <div className="flex rounded-lg border border-border p-0.5 bg-bg" aria-label="图谱视图">{(Object.keys(viewNames) as ViewMode[]).map(v => <button key={v} onClick={() => setMode(v)} disabled={v === 'focus' && !selected} aria-pressed={mode === v} className={clsx('px-3 h-7 text-xs rounded-md disabled:opacity-40', mode === v ? 'bg-primary text-white' : 'text-ts hover:text-tp')}>{viewNames[v]}</button>)}</div>
      <div className="relative min-w-[190px] flex-1 max-w-[280px]"><Search size={14} className="absolute left-2.5 top-2 text-ts" /><input aria-label="搜索全部节点" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索节点，包括隐藏节点" className="h-8 w-full pl-8 pr-3 border border-border rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/30" />
        {search.trim() && <div className="absolute top-9 left-0 right-0 z-30 bg-white border border-border rounded-lg shadow-lg max-h-64 overflow-auto" aria-label="搜索结果">{searchResults.length ? searchResults.map(n => <button key={n.id} onClick={() => selectNode(n.id)} className="w-full px-3 py-2 text-left text-xs hover:bg-bg flex justify-between gap-3"><span>{n.label}</span><span className="text-ts">{NODE_LABEL[n.type] ?? n.type}</span></button>) : <div className="p-3 text-xs text-ts">没有找到匹配节点</div>}</div>}
      </div>
      <label className="text-xs text-ts flex items-center gap-1"><input type="checkbox" checked={keepContext} onChange={e => setKeepContext(e.target.checked)} />保留关联上下文</label><button className={button} onClick={() => setShowList(v => !v)} aria-expanded={showList}>节点列表 {kg?.nodes.length ?? 0}</button><button className={button} onClick={clearOverview}>重置视图</button><button className={button} onClick={() => { setLayoutMode(v => v === 'force' ? 'hierarchy' : 'force'); viewport.current = undefined }} title="切换布局">{layoutMode === 'force' ? '力引导' : '按类型排列'}</button>
    </div>
    <div className="flex flex-1 min-h-0 overflow-hidden">
      <div className="flex-1 min-w-0 relative bg-gradient-to-br from-slate-50 via-blue-50/40 to-indigo-50/30">
        {isLoading && <div className="absolute inset-0 grid place-items-center text-sm text-ts">加载知识图谱...</div>}
        {isError && <div className="absolute inset-0 grid place-items-center text-sm text-ts"><div>图谱加载失败 <button className="text-primary underline" onClick={() => refetch()}>重试</button></div></div>}
        {kg && kg.nodes.length === 0 && <div className="absolute inset-0 grid place-items-center text-sm text-ts">这份文档暂无图谱节点。</div>}
        <svg ref={svgRef} className="w-full h-full block" aria-label="知识图谱画布" />
        <div className="absolute bottom-3 left-3 right-3 flex flex-wrap gap-1.5 pointer-events-none"><button onClick={() => setTypes(new Set())} aria-pressed={types.size === 0} className={clsx('pointer-events-auto h-7 px-2.5 rounded-full text-xs border', types.size === 0 ? 'bg-tp text-white border-tp' : 'bg-white border-border text-ts')}>全部类型</button>{graphTypes.map(t => <button key={t} onClick={() => toggleType(t)} aria-pressed={types.has(t)} className={clsx('pointer-events-auto h-7 px-2.5 rounded-full text-xs border flex items-center gap-1', types.has(t) ? 'bg-tp text-white border-tp' : 'bg-white border-border text-ts')}><span className="w-2 h-2 rounded-full" style={{ background: NODE_COLOR[t] ?? '#94A3B8' }} />{NODE_LABEL[t] ?? t}</button>)}</div>
        {showList && <div className="absolute z-20 top-3 left-3 bottom-14 w-72 max-w-[90%] bg-white border border-border rounded-lg shadow-lg flex flex-col"><div className="px-3 py-3 border-b border-border flex items-center justify-between text-sm font-semibold">全部节点 <button aria-label="关闭节点列表" onClick={() => setShowList(false)}><X size={16}/></button></div><div className="px-3 py-2 text-xs text-ts">包含当前隐藏的 {hiddenCount} 个节点</div><div className="overflow-auto flex-1">{kg?.nodes.map(n => <button key={n.id} onClick={() => selectNode(n.id)} className="w-full text-left px-3 py-2 text-xs hover:bg-bg flex justify-between gap-2"><span>{n.label}</span><span className="text-ts">{NODE_LABEL[n.type] ?? n.type}</span></button>)}</div></div>}
      </div>
      {selected && <aside className="w-72 max-w-[42%] flex-shrink-0 border-l border-border bg-white flex flex-col overflow-hidden" aria-label="节点详情">
        <div className="p-4 border-b border-border flex items-start justify-between gap-2"><div className="min-w-0"><div className="text-sm font-semibold break-words">{selected.label}</div><div className="text-xs text-ts mt-1">{NODE_LABEL[selected.type] ?? selected.type} · {index?.degree.get(selected.id) ?? 0} 个关联节点</div></div><button onClick={() => { setSelectedId(null); setMode(current => current === 'focus' ? 'overview' : current) }} aria-label="关闭详情"><X size={16}/></button></div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs"><div className="flex flex-wrap gap-2"><button className={button} onClick={() => setMode('focus')}>以此为中心</button><button className={button} onClick={() => togglePin(selected.id)}>{pinned.has(selected.id) ? '取消固定显示' : '始终显示'}</button>
          <button className={button} onClick={() => setNeighborExpanded(prev => { const next = new Map(prev); const items = new Set(next.get(selected.id)); const shown = new Set(visible?.nodes.map(n => n.id)); index?.ordered.filter(n => index.neighbors.get(selected.id)?.has(n.id) && !shown.has(n.id)).slice(0, 12).forEach(n => items.add(n.id)); next.set(selected.id, items); return next })} disabled={!index?.ordered.some(n => index.neighbors.get(selected.id)?.has(n.id) && !visible?.nodes.some(v => v.id === n.id))}>展开关联</button>
          {neighborExpanded.has(selected.id) && <button className={button} onClick={() => setNeighborExpanded(prev => { const next = new Map(prev); next.delete(selected.id); return next })}>收起关联</button>}</div>
          <div><div className="font-semibold text-tp mb-2">属性</div>{Object.keys(selected.attributes ?? {}).length ? <dl className="space-y-2">{Object.entries(selected.attributes).map(([key, value]) => <div key={key}><dt className="text-ts">{key}</dt><dd className="mt-0.5 break-words text-tp">{typeof value === 'string' ? value : JSON.stringify(value)}</dd></div>)}</dl> : <p className="text-ts">暂无属性</p>}</div>
          {relatedGroups.length > 0 && mode !== 'all' && <div><div className="font-semibold mb-2">折叠关系</div><div className="space-y-2">{relatedGroups.map(g => <div key={g.id} className="border border-border rounded-lg p-2"><div className="font-medium">{g.relation} · {g.nodes.length} 个</div><div className="flex gap-2 mt-2"><button className="text-primary disabled:opacity-40" disabled={(expanded.get(g.id) ?? 0) >= g.nodes.length} onClick={() => expandGroup(g.id)}>展开更多</button>{expanded.has(g.id) && <button className="text-ts" onClick={() => setExpanded(prev => { const next = new Map(prev); next.delete(g.id); return next })}>收起</button>}</div></div>)}</div></div>}
          <div><div className="font-semibold mb-2">关联关系 · {relatedEdges.length}</div><div className="space-y-1 max-h-60 overflow-auto">{relatedEdges.slice(0, 100).map(e => { const other = index?.nodes.get(e.source === selectedId ? e.target : e.source); return <button key={e.id} onClick={() => other && selectNode(other.id)} className="block w-full text-left p-2 rounded hover:bg-bg text-ts"><span>{e.source === selectedId ? '→' : '←'} {e.relation} </span><span className="text-primary">{other?.label ?? '未知节点'}</span></button> })}{relatedEdges.length > 100 && <p className="text-ts">显示前 100 条，请使用节点列表或搜索查看其他节点。</p>}</div></div>
          <p className="text-ts">原文定位：暂无来源信息</p>
        </div>
      </aside>}
    </div>
  </div>
}
