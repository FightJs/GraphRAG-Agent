import { useRef, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import * as d3 from 'd3'
import { ZoomIn, ZoomOut, Maximize2, Pencil, X, MapPin } from 'lucide-react'
import { kgApi } from '@/services/api'
import type { KGNode, KGEdge } from '@/types'
import { clsx } from 'clsx'

const NODE_COLOR: Record<string, string> = {
  PERSON: '#3B82F6', SKILL: '#22C55E', PROJECT: '#A855F7',
  COMPANY: '#F97316', SCHOOL: '#06B6D4', POSITION: '#EC4899',
}
const NODE_LABEL: Record<string, string> = {
  PERSON: '人物', SKILL: '技能', PROJECT: '项目',
  COMPANY: '公司', SCHOOL: '学校', POSITION: '职位',
}

export default function KGPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)
  const [selected, setSelected] = useState<KGNode | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('ALL')
  const [layoutMode, setLayoutMode] = useState<'force' | 'hierarchy'>('force')

  const { data: kg, isLoading } = useQuery({
    queryKey: ['kg', docId],
    queryFn: () => kgApi.get(docId!),
    enabled: !!docId,
  })

  useEffect(() => {
    if (!kg || !svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth || 800
    const height = svgRef.current.clientHeight || 560

    const filteredNodes = typeFilter === 'ALL' ? kg.nodes : kg.nodes.filter(n => n.type === typeFilter)
    const nodeIds = new Set(filteredNodes.map(n => n.id))
    const filteredEdges = kg.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 3]).on('zoom', (e) => {
      g.attr('transform', e.transform.toString())
    })
    svg.call(zoom)

    const g = svg.append('g')

    // 分层布局：按类型分组分层，层内超出单行容量时自动换行，避免节点重叠
    if (layoutMode === 'hierarchy') {
      const typeGroups = new Map<string, KGNode[]>()
      filteredNodes.forEach(n => {
        if (!typeGroups.has(n.type)) typeGroups.set(n.type, [])
        typeGroups.get(n.type)!.push(n)
      })
      const types = Array.from(typeGroups.keys())
      const MIN_SPACING_X = 90
      const ROW_HEIGHT = 80
      const LAYER_GAP = 50
      const maxPerRow = Math.max(1, Math.floor(width / MIN_SPACING_X))

      let currentY = 60
      types.forEach(type => {
        const nodes = typeGroups.get(type)!
        const rows = Math.ceil(nodes.length / maxPerRow)
        nodes.forEach((n, j) => {
          const row = Math.floor(j / maxPerRow)
          const col = j % maxPerRow
          const nodesInThisRow = Math.min(maxPerRow, nodes.length - row * maxPerRow)
          const rowWidth = nodesInThisRow * MIN_SPACING_X
          const startX = (width - rowWidth) / 2 + MIN_SPACING_X / 2
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
    const edgesForSim = filteredEdges.map(e => ({ ...e }))

    const sim = d3.forceSimulation(filteredNodes as d3.SimulationNodeDatum[])
      .force('link', d3.forceLink(edgesForSim)
        .id((d) => (d as KGNode).id).distance(100))
      .force('charge', layoutMode === 'hierarchy' ? d3.forceManyBody().strength(0) : d3.forceManyBody().strength(-200))
      .force('center', layoutMode === 'hierarchy' ? null : d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(35))

    // Edges
    const link = g.append('g').selectAll('g').data(edgesForSim).enter().append('g')
    link.append('line').attr('stroke', '#CBD5E1').attr('stroke-width', 1.5).attr('marker-end', 'url(#arrow)')
    link.append('text').attr('text-anchor', 'middle').attr('font-size', 10).attr('fill', '#475569').text((d: KGEdge) => d.relation)

    // Arrow marker
    svg.append('defs').append('marker').attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
      .attr('refX', 20).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#CBD5E1')

    // Nodes
    const node = g.append('g').selectAll('g').data(filteredNodes).enter().append('g')
      .style('cursor', 'pointer')
      .call(d3.drag<SVGGElement, KGNode>()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('drag', (e, d) => { (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); (d as d3.SimulationNodeDatum).fx = null; (d as d3.SimulationNodeDatum).fy = null })
      )
      .on('click', (_, d: KGNode) => setSelected(s => s?.id === d.id ? null : d))

    node.append('circle')
      .attr('r', 22)
      .attr('fill', (d: KGNode) => NODE_COLOR[d.type] ?? '#94A3B8')
      .attr('stroke', '#fff').attr('stroke-width', 2)

    node.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('font-size', 10).attr('font-weight', '600').attr('fill', '#1F2937')
      .text((d: KGNode) => d.label.length > 6 ? d.label.slice(0, 6) + '…' : d.label)

    node.append('text').attr('text-anchor', 'middle').attr('dy', '38px')
      .attr('font-size', 9).attr('fill', (d: KGNode) => NODE_COLOR[d.type] ?? '#94A3B8')
      .text((d: KGNode) => NODE_LABEL[d.type] ?? d.type)

    sim.on('tick', () => {
      link.select('line')
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('x1', (d: any) => d.source.x)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('y1', (d: any) => d.source.y)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('x2', (d: any) => d.target.x)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('y2', (d: any) => d.target.y)
      link.select('text')
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      node.attr('transform', (d) => `translate(${(d as any).x},${(d as any).y})`)
    })

    return () => { sim.stop() }
  }, [kg, typeFilter, layoutMode])

  const types = kg ? ['ALL', ...Array.from(new Set(kg.nodes.map(n => n.type)))] : ['ALL']

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
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
                  layoutMode === mode ? 'bg-primary text-white' : 'text-ts hover:text-tp'
                )}
              >
                {mode === 'force' ? '力引导' : '分层'}
              </button>
            ))}
          </div>
          {[ZoomIn, ZoomOut, Maximize2].map((Icon, i) => (
            <button key={i} className="w-8 h-8 border border-border rounded-lg flex items-center justify-center text-ts hover:bg-bg">
              <Icon size={14} />
            </button>
          ))}
          <button
            onClick={() => navigate(`/kb/${kbId}/doc/${docId}/kg/edit`)}
            className="flex items-center gap-1.5 h-8 px-3.5 bg-warning text-white rounded-lg text-xs font-semibold hover:opacity-90"
          >
            <Pencil size={13} /> 进入编辑模式
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1 relative bg-gradient-to-br from-blue-50 to-slate-50">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-ts text-sm">加载知识图谱...</div>
            </div>
          )}
          <svg ref={svgRef} className="w-full h-full" />

          {/* Type filter overlay */}
          <div className="absolute bottom-4 left-4 flex flex-wrap gap-1.5">
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={clsx(
                  'flex items-center gap-1 h-6 px-2.5 rounded-full text-[10px] font-semibold transition-colors',
                  typeFilter === t ? 'bg-tp text-white' : 'bg-surface border border-border text-ts hover:bg-bg'
                )}
              >
                {t !== 'ALL' && <span className="w-2 h-2 rounded-full" style={{ background: NODE_COLOR[t] ?? '#94A3B8' }} />}
                {t === 'ALL' ? '全部' : NODE_LABEL[t] ?? t}
              </button>
            ))}
          </div>
        </div>

        {/* Entity detail panel */}
        <div className={clsx('flex-shrink-0 bg-surface border-l border-border transition-all duration-200 overflow-hidden', selected ? 'w-72' : 'w-0')}>
          {selected && (
            <div className="p-4 h-full flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full" style={{ background: NODE_COLOR[selected.type] ?? '#94A3B8' }} />
                  <span className="font-semibold text-sm text-tp">{selected.label}</span>
                </div>
                <button onClick={() => setSelected(null)} className="text-ts hover:text-tp"><X size={15} /></button>
              </div>
              <div className="space-y-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-ts w-14 flex-shrink-0">类型</span>
                  <span className="px-2 py-0.5 rounded-full font-semibold" style={{ background: (NODE_COLOR[selected.type] ?? '#94A3B8') + '20', color: NODE_COLOR[selected.type] ?? '#94A3B8' }}>
                    {NODE_LABEL[selected.type] ?? selected.type}
                  </span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="text-ts w-14 flex-shrink-0">属性</span>
                  <pre className="bg-slate-900 text-slate-300 rounded-lg p-3 text-[10px] font-mono flex-1 overflow-auto">
                    {JSON.stringify(selected.attributes, null, 2)}
                  </pre>
                </div>
              </div>
              <button className="mt-auto flex items-center justify-center gap-1.5 h-8 border border-border rounded-lg text-xs text-ts hover:bg-bg">
                <MapPin size={12} /> 在文档中定位
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
