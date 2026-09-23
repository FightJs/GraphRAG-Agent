import { useRef, useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate, useBeforeUnload } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import * as d3 from 'd3'
import { Save, X, Undo2, Redo2, PlusCircle, GitMerge, Pencil, ChevronDown, Trash2 } from 'lucide-react'
import { kgApi } from '@/services/api'
import type { KGGraph, KGNode, KGEdge, KGOperation } from '@/types'
import { useToast } from '@/hooks/useToast'
import { clsx } from 'clsx'
import Modal from '@/components/ui/Modal'

const NODE_COLOR: Record<string, string> = {
  PERSON: '#3B82F6', SKILL: '#22C55E', PROJECT: '#A855F7',
  COMPANY: '#F97316', SCHOOL: '#06B6D4', POSITION: '#EC4899',
}
const TYPES = ['PERSON', 'SKILL', 'PROJECT', 'COMPANY', 'SCHOOL', 'POSITION']
const TYPE_LABEL: Record<string, string> = { PERSON:'人物', SKILL:'技能', PROJECT:'项目', COMPANY:'公司', SCHOOL:'学校', POSITION:'职位' }

const uid = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
const cloneGraph = (g: KGGraph): KGGraph => JSON.parse(JSON.stringify(g))

interface Snapshot {
  graph: KGGraph
  ops: KGOperation[]
  changes: number
  selectedId: string | null
  selectedEdgeId: string | null
}

export default function KGEditPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const svgRef = useRef<SVGSVGElement>(null)
  // D3 选中集：选中态变化时只改样式，不重建模拟，避免整图闪动
  const nodeSelRef = useRef<d3.Selection<SVGGElement, KGNode, SVGGElement, unknown> | null>(null)
  const linkSelRef = useRef<d3.Selection<SVGGElement, KGEdge, SVGGElement, unknown> | null>(null)

  const [graph, setGraph] = useState<KGGraph | null>(null)
  const [ops, setOps] = useState<KGOperation[]>([])
  const [selected, setSelected] = useState<KGNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<KGEdge | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editType, setEditType] = useState('')
  const [editAttrs, setEditAttrs] = useState('')
  const [dirty, setDirty] = useState(false)
  const [changes, setChanges] = useState(0)
  const [layoutMode, setLayoutMode] = useState<'force' | 'hierarchy'>('force')

  const [undoStack, setUndoStack] = useState<Snapshot[]>([])
  const [redoStack, setRedoStack] = useState<Snapshot[]>([])

  // 新增节点弹窗
  const [showAddNode, setShowAddNode] = useState(false)
  const [newNodeLabel, setNewNodeLabel] = useState('')
  const [newNodeType, setNewNodeType] = useState('PERSON')
  const [newNodeAttrs, setNewNodeAttrs] = useState('{}')

  // 新增关系弹窗
  const [showAddEdge, setShowAddEdge] = useState(false)
  const [newEdgeSource, setNewEdgeSource] = useState('')
  const [newEdgeTarget, setNewEdgeTarget] = useState('')
  const [newEdgeRelation, setNewEdgeRelation] = useState('')

  const { data: origGraph } = useQuery({ queryKey: ['kg', docId], queryFn: () => kgApi.get(docId!), enabled: !!docId })

  useEffect(() => {
    if (origGraph) {
      setGraph(cloneGraph(origGraph))
      setOps([])
      setUndoStack([])
      setRedoStack([])
      setDirty(false)
      setChanges(0)
      setSelected(null)
      setSelectedEdge(null)
    }
  }, [origGraph])

  useBeforeUnload((e) => { if (dirty) e.preventDefault() })

  useEffect(() => {
    if (selected) {
      setEditLabel(selected.label)
      setEditType(selected.type)
      setEditAttrs(JSON.stringify(selected.attributes, null, 2))
    }
  }, [selected])

  const captureSnapshot = useCallback((): Snapshot | null => {
    if (!graph) return null
    return {
      graph: cloneGraph(graph),
      ops: [...ops],
      changes,
      selectedId: selected?.id ?? null,
      selectedEdgeId: selectedEdge?.id ?? null,
    }
  }, [graph, ops, changes, selected, selectedEdge])

  const pushHistory = useCallback(() => {
    const snap = captureSnapshot()
    if (!snap) return
    setUndoStack(prev => [...prev, snap])
    setRedoStack([])
  }, [captureSnapshot])

  const restoreSnapshot = useCallback((snap: Snapshot) => {
    setGraph(snap.graph)
    setOps(snap.ops)
    setChanges(snap.changes)
    setDirty(snap.ops.length > 0)
    setSelected(snap.selectedId ? snap.graph.nodes.find(n => n.id === snap.selectedId) ?? null : null)
    setSelectedEdge(snap.selectedEdgeId ? snap.graph.edges.find(e => e.id === snap.selectedEdgeId) ?? null : null)
  }, [])

  const undo = useCallback(() => {
    if (!undoStack.length) return
    const snap = captureSnapshot()
    if (!snap) return
    const prev = undoStack[undoStack.length - 1]
    setRedoStack(r => [...r, snap])
    setUndoStack(u => u.slice(0, -1))
    restoreSnapshot(prev)
    toast.info('已撤销')
  }, [undoStack, captureSnapshot, restoreSnapshot, toast])

  const redo = useCallback(() => {
    if (!redoStack.length) return
    const snap = captureSnapshot()
    if (!snap) return
    const next = redoStack[redoStack.length - 1]
    setUndoStack(u => [...u, snap])
    setRedoStack(r => r.slice(0, -1))
    restoreSnapshot(next)
    toast.info('已重做')
  }, [redoStack, captureSnapshot, restoreSnapshot, toast])

  // Ctrl/Cmd+Z 撤销，Ctrl/Cmd+Y 或 Ctrl/Cmd+Shift+Z 重做
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey
      if (!isMod) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return
      if (e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        undo()
      } else if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo])

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
    pushHistory()
    setGraph({
      ...graph,
      nodes: graph.nodes.map(n => n.id === selected.id ? { ...n, label: editLabel, type: editType, attributes: parsedAttrs } : n),
    })
    setSelected(prev => prev ? { ...prev, label: editLabel, type: editType, attributes: parsedAttrs } : prev)
    setOps(prev => [...prev, { op: 'update_node', node_id: selected.id, patch: { label: editLabel, type: editType, attributes: parsedAttrs } }])
    setDirty(true)
    setChanges(c => c + 1)
    toast.success('节点已更新')
  }

  const deleteNode = () => {
    if (!selected || !graph) return
    pushHistory()
    setGraph({
      ...graph,
      nodes: graph.nodes.filter(n => n.id !== selected.id),
      edges: graph.edges.filter(e => e.source !== selected.id && e.target !== selected.id),
    })
    setOps(prev => [...prev, { op: 'delete_node', node_id: selected.id }])
    setSelected(null)
    setSelectedEdge(null)
    setDirty(true)
    setChanges(c => c + 1)
    toast.info('节点已删除')
  }

  const deleteEdge = () => {
    if (!selectedEdge || !graph) return
    pushHistory()
    setGraph({
      ...graph,
      edges: graph.edges.filter(e => e.id !== selectedEdge.id),
    })
    setOps(prev => [...prev, { op: 'delete_edge', edge_id: selectedEdge.id }])
    setSelectedEdge(null)
    setDirty(true)
    setChanges(c => c + 1)
    toast.info('关系已删除')
  }

  const openAddNode = () => {
    setNewNodeLabel('')
    setNewNodeType('PERSON')
    setNewNodeAttrs('{}')
    setShowAddNode(true)
  }

  const confirmAddNode = () => {
    if (!graph) return
    const label = newNodeLabel.trim()
    if (!label) { toast.error('请填写节点标签'); return }
    let parsedAttrs: Record<string, unknown> = {}
    try { parsedAttrs = JSON.parse(newNodeAttrs || '{}') } catch { toast.error('属性 JSON 格式有误'); return }

    const node: KGNode = { id: uid('n'), label, type: newNodeType, attributes: parsedAttrs }
    pushHistory()
    setGraph({
      ...graph,
      nodes: [...graph.nodes, node],
      meta: { ...graph.meta, total_nodes: graph.nodes.length + 1 },
    })
    setOps(prev => [...prev, { op: 'add_node', node }])
    setSelected(node)
    setSelectedEdge(null)
    setDirty(true)
    setChanges(c => c + 1)
    setShowAddNode(false)
    toast.success(`已添加节点「${label}」`)
  }

  const openAddEdge = () => {
    if (!graph || graph.nodes.length < 2) {
      toast.error('至少需要两个节点才能建立关系')
      return
    }
    setNewEdgeSource(selected?.id ?? graph.nodes[0].id)
    setNewEdgeTarget(graph.nodes.find(n => n.id !== (selected?.id ?? ''))?.id ?? graph.nodes[1].id)
    setNewEdgeRelation('')
    setShowAddEdge(true)
  }

  const confirmAddEdge = () => {
    if (!graph) return
    const source = newEdgeSource
    const target = newEdgeTarget
    const relation = newEdgeRelation.trim()
    if (!source || !target) { toast.error('请选择源节点和目标节点'); return }
    if (source === target) { toast.error('源节点与目标节点不能相同'); return }
    if (!relation) { toast.error('请填写关系名称'); return }

    const edge: KGEdge = { id: uid('e'), source, target, relation }
    pushHistory()
    setGraph({
      ...graph,
      edges: [...graph.edges, edge],
      meta: { ...graph.meta, total_edges: graph.edges.length + 1 },
    })
    setOps(prev => [...prev, { op: 'add_edge', edge }])
    setSelected(null)
    setSelectedEdge(edge)
    setDirty(true)
    setChanges(c => c + 1)
    setShowAddEdge(false)
    toast.success(`已添加关系「${relation}」`)
  }

  // D3 rendering —— 仅在 graph / layoutMode 变化时重建模拟
  useEffect(() => {
    if (!graph || !svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = svgRef.current.clientWidth || 800, H = svgRef.current.clientHeight || 500
    const g = svg.append('g')
    svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 3]).on('zoom', e => g.attr('transform', e.transform.toString())))
    svg.on('click', () => { setSelected(null); setSelectedEdge(null) })

    // 分层布局：按类型分组分层，层内超出单行容量时自动换行，避免节点重叠
    if (layoutMode === 'hierarchy') {
      const typeGroups = new Map<string, KGNode[]>()
      graph.nodes.forEach(n => {
        if (!typeGroups.has(n.type)) typeGroups.set(n.type, [])
        typeGroups.get(n.type)!.push(n)
      })
      const types = Array.from(typeGroups.keys())
      const MIN_SPACING_X = 130
      const ROW_HEIGHT = 110
      const LAYER_GAP = 72
      const maxPerRow = Math.max(1, Math.floor((W - 48) / MIN_SPACING_X))

      let currentY = 64
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
    } else {
      // 力引导：按连通分量紧挨着摆，避免团与团被摊到画布四角
      const neighbors = new Map<string, Set<string>>()
      graph.edges.forEach(e => {
        if (!neighbors.has(e.source)) neighbors.set(e.source, new Set())
        if (!neighbors.has(e.target)) neighbors.set(e.target, new Set())
        neighbors.get(e.source)!.add(e.target)
        neighbors.get(e.target)!.add(e.source)
      })
      const byId = new Map(graph.nodes.map(n => [n.id, n]))
      const visited = new Set<string>()
      const components: KGNode[][] = []
      graph.nodes.forEach(n => {
        if (visited.has(n.id)) return
        const stack = [n]
        const comp: KGNode[] = []
        visited.add(n.id)
        while (stack.length) {
          const cur = stack.pop()!
          comp.push(cur)
          neighbors.get(cur.id)?.forEach(id => {
            if (visited.has(id)) return
            visited.add(id)
            const next = byId.get(id)
            if (next) stack.push(next)
          })
        }
        components.push(comp)
      })
      components.sort((a, b) => b.length - a.length)

      const packRadius = (size: number) => Math.max(40, 32 + Math.sqrt(size) * 22)
      const GAP = 96
      components.forEach((comp, i) => {
        const sn0 = comp[0] as d3.SimulationNodeDatum
        // 已有坐标（拖过/切布局）则保留
        if (sn0.x != null && sn0.y != null) {
          comp.forEach(n => {
            const sn = n as d3.SimulationNodeDatum
            sn.fx = null
            sn.fy = null
          })
          return
        }
        const rIn = packRadius(comp.length)
        let bx = W / 2
        let by = H / 2
        if (i > 0) {
          const angle = (i - 1) * 2.399963
          const dist = packRadius(components[0].length) + rIn + GAP
          bx = W / 2 + Math.cos(angle) * dist
          by = H / 2 + Math.sin(angle) * dist
        }
        comp.forEach((n, j) => {
          const sn = n as d3.SimulationNodeDatum
          sn.fx = null
          sn.fy = null
          const a = (j / Math.max(comp.length, 1)) * Math.PI * 2
          const r = rIn * (0.4 + 0.5 * ((j % 4) / 4))
          sn.x = bx + Math.cos(a) * r
          sn.y = by + Math.sin(a) * r
        })
      })
    }

    // forceLink 会把 edge.source/target 字符串就地解析为节点对象引用，
    // 必须让 DOM 绑定的数据和喂给 forceLink 的数据是同一份数组/对象，
    // 否则 tick 时 d.source.x 仍是字符串上取属性，得到 NaN，线条整条不渲染。
    const edgesForSim = graph.edges.map(e => ({ ...e }))

    // 计算度数，高连接度节点斥力更强，避免中心堆叠
    const degree = new Map<string, number>()
    graph.nodes.forEach(n => degree.set(n.id, 0))
    graph.edges.forEach(e => {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
    })

    const isForce = layoutMode === 'force'
    const sim = d3.forceSimulation(graph.nodes as d3.SimulationNodeDatum[])
      .force('link', d3.forceLink(edgesForSim).id((d) => (d as KGNode).id).distance(130).strength(0.7))
      .force('charge', isForce
        ? d3.forceManyBody()
          .strength((d) => -240 - ((degree.get((d as KGNode).id) ?? 0) * 16))
          .distanceMax(380)
          .theta(0.9)
        : d3.forceManyBody().strength(0))
      .force('center', isForce ? d3.forceCenter(W / 2, H / 2).strength(0.05) : null)
      .force('collision', d3.forceCollide(50).iterations(2))
      .force('x', isForce ? d3.forceX(W / 2).strength(0.03) : null)
      .force('y', isForce ? d3.forceY(H / 2).strength(0.03) : null)
      .alphaDecay(0.035)
      .velocityDecay(0.4)

    // Arrow marker for edges
    svg.append('defs').append('marker').attr('id', 'arrow-edit').attr('viewBox', '0 -5 10 10')
      .attr('refX', 22).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#94A3B8')

    // 选中边时用高亮 marker
    svg.append('defs').append('marker').attr('id', 'arrow-edit-active').attr('viewBox', '0 -5 10 10')
      .attr('refX', 22).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#D97706')

    const link = g.append('g').selectAll<SVGGElement, KGEdge>('g').data(edgesForSim).enter().append('g').style('cursor', 'pointer')
      .on('click', (event: MouseEvent, d: KGEdge) => {
        event.stopPropagation()
        setSelected(null)
        setSelectedEdge(prev => prev?.id === d.id ? null : d)
      })
    link.append('line').attr('class', 'edge-line')
      .attr('stroke', '#CBD5E1')
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrow-edit)')
    // 加宽透明线，便于点选
    link.append('line')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 14)
    link.append('text').attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('fill', '#64748B')
      .text((d: KGEdge) => d.relation)

    const node = g.append('g').selectAll<SVGGElement, KGNode>('g').data(graph.nodes).enter().append('g').style('cursor', 'pointer')
      .call(d3.drag<SVGGElement, KGNode>()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('drag', (e, d) => { (d as d3.SimulationNodeDatum).fx = e.x; (d as d3.SimulationNodeDatum).fy = e.y })
        .on('end', (e, d) => {
          if (!e.active) sim.alphaTarget(0)
          if (layoutMode !== 'hierarchy') {
            // 拖完短暂固定再放开，避免立刻被弹回
            const sn = d as d3.SimulationNodeDatum
            sn.fx = sn.x
            sn.fy = sn.y
            window.setTimeout(() => { sn.fx = null; sn.fy = null }, 80)
          }
        })
      )
      .on('click', (event: MouseEvent, d: KGNode) => {
        event.stopPropagation()
        setSelectedEdge(null)
        setSelected(s => s?.id === d.id ? null : d)
      })

    node.append('circle').attr('class', 'node-circle').attr('r', 24)
      .attr('fill', (d: KGNode) => NODE_COLOR[d.type] ?? '#94A3B8')
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)
    node.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em').attr('font-size', 10).attr('font-weight', '600').attr('fill', '#1F2937')
      .text((d: KGNode) => d.label.length > 6 ? d.label.slice(0, 6) + '…' : d.label)

    nodeSelRef.current = node
    linkSelRef.current = link

    type NodeWithXY = d3.SimulationNodeDatum & { x: number; y: number }
    sim.on('tick', () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      link.selectAll('line')
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('x1', (d: any) => (d.source as NodeWithXY).x)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('y1', (d: any) => (d.source as NodeWithXY).y)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('x2', (d: any) => (d.target as NodeWithXY).x)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('y2', (d: any) => (d.target as NodeWithXY).y)
      link.select('text')
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('x', (d: any) => ((d.source as NodeWithXY).x + (d.target as NodeWithXY).x) / 2)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .attr('y', (d: any) => ((d.source as NodeWithXY).y + (d.target as NodeWithXY).y) / 2 - 4)
      node.attr('transform', (d) => `translate(${(d as unknown as NodeWithXY).x},${(d as unknown as NodeWithXY).y})`)
    })
    return () => {
      sim.stop()
      nodeSelRef.current = null
      linkSelRef.current = null
    }
  }, [graph, layoutMode])

  // 选中态高亮：只改 stroke / opacity，不触发模拟重建
  useEffect(() => {
    const node = nodeSelRef.current
    const link = linkSelRef.current
    if (!node || !link) return
    const selId = selected?.id ?? null
    const selEdgeId = selectedEdge?.id ?? null

    node.select('.node-circle')
      .attr('stroke', (d: KGNode) => d.id === selId ? '#D97706' : '#fff')
      .attr('stroke-width', (d: KGNode) => d.id === selId ? 3.5 : 2)

    node.style('opacity', (d: KGNode) => {
      if (!selId && !selEdgeId) return 1
      if (selId) return d.id === selId ? 1 : 0.45
      return 1
    })

    link.select('.edge-line')
      .attr('stroke', (d: KGEdge) => d.id === selEdgeId ? '#D97706' : '#CBD5E1')
      .attr('stroke-width', (d: KGEdge) => d.id === selEdgeId ? 2.8 : 1.5)
      .attr('marker-end', (d: KGEdge) => d.id === selEdgeId ? 'url(#arrow-edit-active)' : 'url(#arrow-edit)')

    link.select('.edge-label')
      .attr('fill', (d: KGEdge) => d.id === selEdgeId ? '#D97706' : '#64748B')
      .attr('font-weight', (d: KGEdge) => d.id === selEdgeId ? 600 : 400)

    link.style('opacity', (d: KGEdge) => {
      if (!selEdgeId) return 1
      return d.id === selEdgeId ? 1 : 0.35
    })
  }, [selected?.id, selectedEdge?.id])

  const nodeLabel = (id: string) => graph?.nodes.find(n => n.id === id)?.label ?? id

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
          <button onClick={openAddNode} disabled={!graph}
            className="w-full flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed">
            <PlusCircle size={14} />新增节点
          </button>
          <button onClick={openAddEdge} disabled={!graph || graph.nodes.length < 2}
            className="w-full flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-tp border border-border hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
            title={graph && graph.nodes.length < 2 ? '至少需要两个节点' : undefined}>
            <GitMerge size={14} />新增关系
          </button>
          <button onClick={undo} disabled={!undoStack.length}
            className="flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-tp border border-border hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
            <Undo2 size={14} />撤销 (Ctrl+Z)
          </button>
          <button onClick={redo} disabled={!redoStack.length}
            className="flex items-center gap-2 h-9 px-2.5 rounded-lg text-xs bg-bg text-tp border border-border hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
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

        {/* Canvas —— 右侧面板用浮层，不改变画布宽度，避免选中时视角跳动 */}
        <div className="flex-1 relative bg-gradient-to-br from-amber-50/40 to-slate-50" style={{ outline: '2px solid #D97706', outlineOffset: '-2px' }}>
          <svg ref={svgRef} className="w-full h-full" />

          {/* Right attribute panel — node */}
          {selected && (
            <div className="absolute right-0 top-0 bottom-0 w-72 border-l border-border bg-surface flex flex-col shadow-xl z-10">
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

          {/* Right attribute panel — edge */}
          {selectedEdge && !selected && (
            <div className="absolute right-0 top-0 bottom-0 w-72 border-l border-border bg-surface flex flex-col shadow-xl z-10">
              <div className="flex items-center justify-between p-4 border-b border-border">
                <span className="text-sm font-semibold text-tp">关系属性</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-700">
                  关系
                </span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                <div>
                  <label className="block text-[11px] font-semibold text-ts mb-1.5">关系名称</label>
                  <input value={selectedEdge.relation} readOnly
                    className="w-full h-9 px-3 border border-border rounded-lg text-sm bg-slate-50 text-tp" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-ts mb-1.5">源节点</label>
                  <input value={nodeLabel(selectedEdge.source)} readOnly
                    className="w-full h-9 px-3 border border-border rounded-lg text-sm bg-slate-50 text-tp" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-ts mb-1.5">目标节点</label>
                  <input value={nodeLabel(selectedEdge.target)} readOnly
                    className="w-full h-9 px-3 border border-border rounded-lg text-sm bg-slate-50 text-tp" />
                </div>
              </div>
              <div className="p-4 border-t border-border">
                <button onClick={deleteEdge} className="w-full flex items-center justify-center gap-2 h-9 bg-red-50 border border-danger text-danger rounded-lg text-sm font-semibold hover:bg-red-100">
                  <Trash2 size={14} /> 删除该关系
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 新增节点弹窗 */}
      <Modal open={showAddNode} onClose={() => setShowAddNode(false)} title="新增节点" width="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowAddNode(false)}
              className="h-9 px-4 rounded-lg text-sm border border-border text-ts hover:bg-slate-50">取消</button>
            <button onClick={confirmAddNode}
              className="h-9 px-4 rounded-lg text-sm bg-primary text-white font-semibold hover:bg-primary-hover">添加</button>
          </div>
        }>
        <div className="space-y-4">
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">节点标签 (label) *</label>
            <input value={newNodeLabel} onChange={e => setNewNodeLabel(e.target.value)}
              placeholder="例如：张三 / LangChain / 某某公司"
              autoFocus
              onKeyDown={e => { if (e.key === 'Enter') confirmAddNode() }}
              className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">实体类型 (type)</label>
            <div className="relative">
              <select value={newNodeType} onChange={e => setNewNodeType(e.target.value)}
                className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none appearance-none bg-surface">
                {TYPES.map(t => <option key={t} value={t}>{TYPE_LABEL[t]} ({t})</option>)}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-ts pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">属性 (attributes，JSON，可选)</label>
            <textarea value={newNodeAttrs} onChange={e => setNewNodeAttrs(e.target.value)} rows={4}
              placeholder='{"key": "value"}'
              className="w-full px-3 py-2 border border-border rounded-lg text-xs font-mono bg-slate-900 text-slate-300 focus:outline-none resize-none" />
          </div>
        </div>
      </Modal>

      {/* 新增关系弹窗 */}
      <Modal open={showAddEdge} onClose={() => setShowAddEdge(false)} title="新增关系" width="max-w-md"
        footer={
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowAddEdge(false)}
              className="h-9 px-4 rounded-lg text-sm border border-border text-ts hover:bg-slate-50">取消</button>
            <button onClick={confirmAddEdge}
              className="h-9 px-4 rounded-lg text-sm bg-primary text-white font-semibold hover:bg-primary-hover">添加</button>
          </div>
        }>
        <div className="space-y-4">
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">源节点 *</label>
            <div className="relative">
              <select value={newEdgeSource} onChange={e => setNewEdgeSource(e.target.value)}
                className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none appearance-none bg-surface">
                {graph?.nodes.map(n => (
                  <option key={n.id} value={n.id}>{n.label}（{TYPE_LABEL[n.type] ?? n.type}）</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-ts pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">目标节点 *</label>
            <div className="relative">
              <select value={newEdgeTarget} onChange={e => setNewEdgeTarget(e.target.value)}
                className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none appearance-none bg-surface">
                {graph?.nodes.map(n => (
                  <option key={n.id} value={n.id}>{n.label}（{TYPE_LABEL[n.type] ?? n.type}）</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-ts pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ts mb-1.5">关系名称 *</label>
            <input value={newEdgeRelation} onChange={e => setNewEdgeRelation(e.target.value)}
              placeholder="例如：就职于 / 掌握 / 毕业于"
              autoFocus
              onKeyDown={e => { if (e.key === 'Enter') confirmAddEdge() }}
              className="w-full h-9 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
          </div>
        </div>
      </Modal>
    </div>
  )
}
