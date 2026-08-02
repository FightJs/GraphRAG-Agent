import { useRef, useEffect, useState } from 'react'
import { useParams, useNavigate, useBeforeUnload } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import * as d3 from 'd3'
import { Save, X, Undo2, Redo2, PlusCircle, GitMerge, Pencil, ChevronDown, Trash2, Construction } from 'lucide-react'
import { kgApi } from '@/services/api'
import type { KGGraph, KGNode, KGEdge, KGOperation } from '@/types'
import { useToast } from '@/hooks/useToast'
import { clsx } from 'clsx'

const NODE_COLOR: Record<string, string> = {
  PERSON: '#3B82F6', SKILL: '#22C55E', PROJECT: '#A855F7',
  COMPANY: '#F97316', SCHOOL: '#06B6D4', POSITION: '#EC4899',
}
const TYPES = ['PERSON', 'SKILL', 'PROJECT', 'COMPANY', 'SCHOOL', 'POSITION']
const TYPE_LABEL: Record<string, string> = { PERSON:'人物', SKILL:'技能', PROJECT:'项目', COMPANY:'公司', SCHOOL:'学校', POSITION:'职位' }

export default function KGEditPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const svgRef = useRef<SVGSVGElement>(null)

  const [graph, setGraph] = useState<KGGraph | null>(null)
  const [ops, setOps] = useState<KGOperation[]>([])
  const [selected, setSelected] = useState<KGNode | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editType, setEditType] = useState('')
  const [editAttrs, setEditAttrs] = useState('')
  const [dirty, setDirty] = useState(false)
  const [changes, setChanges] = useState(0)
  const [layoutMode, setLayoutMode] = useState<'force' | 'hierarchy'>('force')

  const { data: origGraph } = useQuery({ queryKey: ['kg', docId], queryFn: () => kgApi.get(docId!), enabled: !!docId })

  useEffect(() => { if (origGraph) setGraph(JSON.parse(JSON.stringify(origGraph))) }, [origGraph])

  useBeforeUnload((e) => { if (dirty) e.preventDefault() })

  useEffect(() => {
    if (selected) {
      setEditLabel(selected.label)
      setEditType(selected.type)
      setEditAttrs(JSON.stringify(selected.attributes, null, 2))
    }
  }, [selected])

  const saveMut = useMutation({
    mutationFn: () => kgApi.save(docId!, ops),
    onSuccess: () => {
      toast.success(`KG 已更新（修改了 ${changes} 处）`)
      setDirty(false)
      setOps([])
      navigate(`/kb/${kbId}/doc/${docId}/kg`)
    },
    onError: () => toast.error('保存失败，请重试'),
  })

  const applyEdit = () => {
    if (!selected || !graph) return
    let parsedAttrs: Record<string, unknown> = {}
    try { parsedAttrs = JSON.parse(editAttrs) } catch { toast.error('属性 JSON 格式有误'); return }
    setGraph({
      ...graph,
      nodes: graph.nodes.map(n => n.id === selected.id ? { ...n, label: editLabel, type: editType, attributes: parsedAttrs } : n),
    })
    setSelected(prev => prev ? { ...prev, label: editLabel, type: editType, attributes: parsedAttrs } : prev)
    // Track as update_node operation
    setOps(prev => [...prev, { op: 'update_node', node_id: selected.id, patch: { label: editLabel, type: editType, attributes: parsedAttrs } }])
    setDirty(true)
    setChanges(c => c + 1)
    toast.success('节点已更新')
  }

  const deleteNode = () => {
    if (!selected || !graph) return
    setGraph({
      ...graph,
      nodes: graph.nodes.filter(n => n.id !== selected.id),
      edges: graph.edges.filter(e => e.source !== selected.id && e.target !== selected.id),
    })
    // Track as delete_node operation
    setOps(prev => [...prev, { op: 'delete_node', node_id: selected.id }])
    setSelected(null)
    setDirty(true)
    setChanges(c => c + 1)
    toast.info('节点已删除')
  }

  // D3 rendering
  useEffect(() => {
    if (!graph || !svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = svgRef.current.clientWidth || 800, H = svgRef.current.clientHeight || 500
    const g = svg.append('g')
    svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 3]).on('zoom', e => g.attr('transform', e.transform.toString())))

    // 分层布局：按类型分组分层，层内超出单行容量时自动换行，避免节点重叠
    if (layoutMode === 'hierarchy') {
      const typeGroups = new Map<string, KGNode[]>()
      graph.nodes.forEach(n => {
        if (!typeGroups.has(n.type)) typeGroups.set(n.type, [])
        typeGroups.get(n.type)!.push(n)
      })
      const types = Array.from(typeGroups.keys())
      const MIN_SPACING_X = 90
      const ROW_HEIGHT = 80
      const LAYER_GAP = 50
      const maxPerRow = Math.max(1, Math.floor(W / MIN_SPACING_X))

      let currentY = 60
      types.forEach(type => {
        const nodes = typeGroups.get(type)!
        const rows = Math.ceil(nodes.length / maxPerRow)
        nodes.forEach((n, j) => {
          const row = Math.floor(j / maxPerRow)
          const col = j % maxPerRow
          const nodesInThisRow = Math.min(maxPerRow, nodes.length - row * maxPerRow)
          const rowWidth = nodesInThisRow * MIN_SPACING_X
          const startX = (W - rowWidth) / 2 + MIN_SPACING_X / 2
          const sn = n as d3.SimulationNodeDatum
          sn.x = startX + col * MIN_SPACING_X
          sn.y = currentY + row * ROW_HEIGHT
          sn.fx = sn.x
          sn.fy = sn.y
        })
        currentY += rows * ROW_HEIGHT + LAYER_GAP
      })
    }

    // forceLink 会把 edge.source/target 字符串就地解析为节点对象引用，
    // 必须让 DOM 绑定的数据和喂给 forceLink 的数据是同一份数组/对象，
    // 否则 tick 时 d.source.x 仍是字符串上取属性，得到 NaN，线条整条不渲染。
    const edgesForSim = graph.edges.map(e => ({ ...e }))

    const sim = d3.forceSimulation(graph.nodes as d3.SimulationNodeDatum[])
      .force('link', d3.forceLink(edgesForSim).id((d) => (d as KGNode).id).distance(100))
      .force('charge', layoutMode === 'hierarchy' ? d3.forceManyBody().strength(0) : d3.forceManyBody().strength(-200))
      .force('center', layoutMode === 'hierarchy' ? null : d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide(32))

    // Arrow marker for edges
    svg.append('defs').append('marker').attr('id', 'arrow-edit').attr('viewBox', '0 -5 10 10')
      .attr('refX', 20).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#94A3B8')

    const link = g.append('g').selectAll('line').data(edgesForSim).enter().append('line')
      .attr('stroke', '#CBD5E1').attr('stroke-width', 1.5).attr('marker-end', 'url(#arrow-edit)')
    const node = g.append('g').selectAll('g').data(graph.nodes).enter().append('g').style('cursor', 'pointer')
      .call(d3.drag<SVGGElement, KGNode>()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('drag', (e, d) => { (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); (d as d3.SimulationNodeDatum).fx = null; (d as d3.SimulationNodeDatum).fy = null })
      )
      .on('click', (_, d: KGNode) => setSelected(s => s?.id === d.id ? null : d))

    node.append('circle').attr('r', 22)
      .attr('fill', (d: KGNode) => NODE_COLOR[d.type] ?? '#94A3B8')
      .attr('stroke', (d: KGNode) => selected?.id === d.id ? '#D97706' : '#fff')
      .attr('stroke-width', (d: KGNode) => selected?.id === d.id ? 3 : 2)
    node.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em').attr('font-size', 10).attr('font-weight', '600').attr('fill', '#1F2937')
      .text((d: KGNode) => d.label.length > 6 ? d.label.slice(0, 6) + '…' : d.label)

    type NodeWithXY = d3.SimulationNodeDatum & { x: number; y: number }
    sim.on('tick', () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      link.attr('x1', (d: any) => (d.source as NodeWithXY).x)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('y1', (d: any) => (d.source as NodeWithXY).y)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('x2', (d: any) => (d.target as NodeWithXY).x)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('y2', (d: any) => (d.target as NodeWithXY).y)
      node.attr('transform', (d) => `translate(${(d as unknown as NodeWithXY).x},${(d as unknown as NodeWithXY).y})`)
    })
    return () => { sim.stop() }
  }, [graph, selected?.id, layoutMode])

  return (
    <div className="h-full flex flex-col">
      {/* Edit mode banner */}
      <div className="bg-amber-50 border-b border-amber-200 flex items-center justify-between px-6 py-2.5 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Pencil size={14} className="text-amber-700" />
          <span className="text-sm font-semibold text-amber-700">
            编辑模式已开启{dirty ? `，变更未保存（${changes} 处修改）` : '，尚未修改'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => saveMut.mutate()} disabled={!dirty || saveMut.isPending}
            className="flex items-center gap-1.5 h-8 px-3.5 bg-warning text-white rounded-lg text-xs font-semibold hover:opacity-90 disabled:opacity-40">
            <Save size={13} />{saveMut.isPending ? '保存中...' : '保存更改'}
          </button>
          <button onClick={() => { if (dirty && !confirm('有未保存的修改，确认放弃？')) return; navigate(`/kb/${kbId}/doc/${docId}/kg`) }}
            className="flex items-center gap-1.5 h-8 px-3.5 border border-amber-300 text-amber-700 rounded-lg text-xs font-semibold hover:bg-amber-100">
            <X size={13} /> 放弃更改
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left tool panel */}
        <div className="w-48 border-r border-border bg-surface flex-shrink-0 flex flex-col gap-1 p-3">
          <p className="text-[10px] font-semibold text-ts mb-1">布局方式</p>
          <div className="flex items-center gap-1 h-8 px-1 bg-bg border border-border rounded-lg mb-2">
            {(['force', 'hierarchy'] as const).map(mode => (
              <button
                key={mode}
                onClick={() => setLayoutMode(mode)}
                className={clsx(
                  'flex-1 h-6 rounded text-[11px] font-medium transition-colors',
                  layoutMode === mode ? 'bg-primary text-white' : 'text-ts hover:text-tp'
                )}
              >
                {mode === 'force' ? '力引导' : '分层'}
              </button>
            ))}
          </div>
          <p className="text-[10px] font-semibold text-ts mb-1">编辑工具</p>
          {/* 新增节点/关系：后端支持，前端交互未实现 */}
          <div className="relative group">
            <button disabled className="w-full flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-primary/10 text-primary border border-primary/30 opacity-50 cursor-not-allowed">
              <PlusCircle size={14} />新增节点
            </button>
            <span className="absolute right-1 top-1 flex items-center gap-0.5 text-[9px] bg-amber-100 text-amber-700 px-1 py-0.5 rounded">
              <Construction size={9} />未开发
            </span>
          </div>
          <div className="relative group">
            <button disabled className="w-full flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-ts border border-border opacity-50 cursor-not-allowed">
              <GitMerge size={14} />新增关系
            </button>
            <span className="absolute right-1 top-1 flex items-center gap-0.5 text-[9px] bg-amber-100 text-amber-700 px-1 py-0.5 rounded">
              <Construction size={9} />未开发
            </span>
          </div>
          <button disabled className="flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-ts border border-border opacity-40 cursor-not-allowed">
            <Undo2 size={14} />撤销 (Ctrl+Z)
          </button>
          <button disabled className="flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-ts border border-border opacity-40 cursor-not-allowed">
            <Redo2 size={14} />重做 (Ctrl+Y)
          </button>
          <div className="border-t border-border my-2" />
          <p className="text-[10px] font-semibold text-ts mb-1">图例</p>
          {TYPES.map(t => (
            <div key={t} className="flex items-center gap-2 h-6">
              <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: NODE_COLOR[t] }} />
              <span className="text-[11px] text-ts">{TYPE_LABEL[t]}</span>
            </div>
          ))}
        </div>

        {/* Canvas */}
        <div className="flex-1 relative bg-gradient-to-br from-amber-50/40 to-slate-50" style={{ outline: '2px solid #D97706', outlineOffset: '-2px' }}>
          <svg ref={svgRef} className="w-full h-full" />
        </div>

        {/* Right attribute panel */}
        {selected && (
          <div className="w-72 border-l border-border bg-surface flex-shrink-0 flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <span className="text-sm font-semibold text-tp">节点属性</span>
              <span className="text-xs px-2 py-0.5 rounded-full font-semibold" style={{ background: (NODE_COLOR[selected.type] ?? '#94A3B8') + '20', color: NODE_COLOR[selected.type] ?? '#94A3B8' }}>
                {TYPE_LABEL[selected.type] ?? selected.type}
              </span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <label className="block text-[11px] font-semibold text-ts mb-1.5">节点标签 (label)</label>
                <input value={editLabel} onChange={e => setEditLabel(e.target.value)}
                  className="w-full h-9 px-3 border-2 border-warning rounded-lg text-sm focus:outline-none" />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-ts mb-1.5">实体类型 (type)</label>
                <div className="relative">
                  <select value={editType} onChange={e => setEditType(e.target.value)}
                    className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none appearance-none bg-surface">
                    {TYPES.map(t => <option key={t} value={t}>{TYPE_LABEL[t]} ({t})</option>)}
                  </select>
                  <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-ts pointer-events-none" />
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-ts mb-1.5">属性 (attributes)</label>
                <textarea value={editAttrs} onChange={e => setEditAttrs(e.target.value)} rows={6}
                  className="w-full px-3 py-2 border border-border rounded-lg text-xs font-mono bg-slate-900 text-slate-300 focus:outline-none resize-none" />
              </div>
              <button onClick={applyEdit} className="w-full h-9 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover">
                应用修改
              </button>
            </div>
            <div className="p-4 border-t border-border">
              <button onClick={deleteNode} className="w-full flex items-center justify-center gap-2 h-9 bg-red-50 border border-danger text-danger rounded-lg text-sm font-semibold hover:bg-red-100">
                <Trash2 size={14} /> 删除该节点
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
