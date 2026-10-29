import type { KGEdge, KGGraph, KGNode } from '@/types'

export interface GraphGroup {
  id: string
  source: string
  relation: string
  nodes: KGNode[]
  edges: KGEdge[]
}

export interface GraphIndex {
  nodes: Map<string, KGNode>
  neighbors: Map<string, Set<string>>
  degree: Map<string, number>
  groups: GraphGroup[]
  groupedIds: Set<string>
  ordered: KGNode[]
}

// Groups are presentation-only, restricted to repeated relations to single-neighbor OTHER nodes.
export function buildGraphIndex(graph: KGGraph): GraphIndex {
  const nodes = new Map(graph.nodes.map(n => [n.id, n]))
  const neighbors = new Map(graph.nodes.map(n => [n.id, new Set<string>()]))
  const relations = new Map<string, Set<string>>()
  for (const e of graph.edges) {
    if (!nodes.has(e.source) || !nodes.has(e.target)) continue
    neighbors.get(e.source)!.add(e.target)
    neighbors.get(e.target)!.add(e.source)
    for (const id of [e.source, e.target]) {
      if (!relations.has(id)) relations.set(id, new Set())
      relations.get(id)!.add(e.relation)
    }
  }
  const degree = new Map([...neighbors].map(([id, items]) => [id, items.size]))
  const candidates = new Map<string, { source: string; relation: string; nodes: Map<string, KGNode>; edges: KGEdge[] }>()
  for (const edge of graph.edges) {
    const target = nodes.get(edge.target)
    if (!target || target.type !== 'OTHER' || degree.get(target.id) !== 1 || edge.source === edge.target) continue
    const relation = edge.relation === '购买了' ? '购买' : edge.relation
    if (!['购买', '点了'].includes(relation)) continue
    const key = JSON.stringify([edge.source, relation])
    const group = candidates.get(key) ?? { source: edge.source, relation, nodes: new Map<string, KGNode>(), edges: [] as KGEdge[] }
    group.nodes.set(target.id, target)
    group.edges.push(edge)
    candidates.set(key, group)
  }
  const groups: GraphGroup[] = [...candidates.entries()].filter(([, g]) => g.nodes.size >= 4).map(([key, g]) => ({
    id: `__kg_group__${key}`, source: g.source, relation: g.relation,
    nodes: [...g.nodes.values()].sort((a, b) => a.label.localeCompare(b.label, 'zh-CN') || a.id.localeCompare(b.id)), edges: g.edges,
  }))
  const groupedIds = new Set(groups.flatMap(g => g.nodes.map(n => n.id)))
  const score = (n: KGNode) => Math.log1p(degree.get(n.id) ?? 0) * 2 + Math.log1p(relations.get(n.id)?.size ?? 0) + (n.type === 'PERSON' ? 0.8 : 0)
  const ordered = [...graph.nodes].filter(n => !groupedIds.has(n.id)).sort((a, b) => score(b) - score(a) || a.id.localeCompare(b.id))
  return { nodes, neighbors, degree, groups, groupedIds, ordered }
}

export type ViewMode = 'overview' | 'focus' | 'all'
export interface ViewResult { nodes: KGNode[]; edges: KGEdge[]; groups: GraphGroup[]; realCount: number; hiddenCount: number }

export function buildVisibleGraph(graph: KGGraph, index: GraphIndex, options: {
  mode: ViewMode; selectedId: string | null; expanded: Map<string, number>; pinned: Set<string>; revealed: Set<string>; types: Set<string>; keepContext?: boolean
}): ViewResult {
  const { mode, selectedId, expanded, pinned, revealed, types } = options
  const visible = new Set<string>()
  if (mode === 'all') graph.nodes.forEach(n => visible.add(n.id))
  else if (mode === 'focus' && selectedId && index.nodes.has(selectedId)) {
    visible.add(selectedId)
    const near = index.neighbors.get(selectedId) ?? new Set<string>()
    index.ordered.filter(n => near.has(n.id)).slice(0, 25).forEach(n => visible.add(n.id))
  } else index.ordered.slice(0, 30).forEach(n => visible.add(n.id))
  pinned.forEach(id => visible.add(id))
  revealed.forEach(id => visible.add(id))
  if (selectedId && index.nodes.has(selectedId)) visible.add(selectedId)
  const groupNodes: KGNode[] = []
  const groupEdges: KGEdge[] = []
  const shownGroups: GraphGroup[] = []
  if (mode !== 'all') for (const g of index.groups) {
    if (!visible.has(g.source)) continue
    const count = Math.min(expanded.get(g.id) ?? 0, g.nodes.length)
    g.nodes.slice(0, count).forEach(n => visible.add(n.id))
    const hidden = g.nodes.filter(n => !visible.has(n.id)).length
    if (hidden > 0) {
      shownGroups.push(g)
      groupNodes.push({ id: g.id, label: `${g.relation} · ${hidden}`, type: '__GROUP__', attributes: {} })
      groupEdges.push({ id: `__edge__${g.id}`, source: g.source, target: g.id, relation: g.relation })
    }
  }
  const allowed = (n: KGNode) => types.size === 0 || types.has(n.type) || pinned.has(n.id) || n.id === selectedId || revealed.has(n.id)
  const primary = graph.nodes.filter(n => visible.has(n.id) && allowed(n))
  const context = new Set(primary.map(n => n.id))
  if (types.size && options.keepContext) {
    for (const n of primary) index.neighbors.get(n.id)?.forEach(id => { if (visible.has(id)) context.add(id) })
  }
  const realNodes = graph.nodes.filter(n => context.has(n.id))
  const ids = new Set(realNodes.map(n => n.id))
  const keptGroups = groupNodes.filter(n => {
    const g = index.groups.find(item => item.id === n.id)!
    return ids.has(g.source) && (types.size === 0 || types.has('OTHER'))
  })
  const keptIds = new Set(keptGroups.map(n => n.id))
  return {
    nodes: [...realNodes, ...keptGroups],
    edges: [...graph.edges.filter(e => ids.has(e.source) && ids.has(e.target)), ...groupEdges.filter(e => keptIds.has(e.target))],
    groups: shownGroups.filter(g => keptIds.has(g.id)), realCount: realNodes.length, hiddenCount: graph.nodes.length - realNodes.length,
  }
}
