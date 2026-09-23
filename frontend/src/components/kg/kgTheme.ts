import type { KGNode, KGEdge } from '@/types'
import * as d3 from 'd3'

export const NODE_COLOR: Record<string, string> = {
  PERSON: '#3B82F6',
  SKILL: '#22C55E',
  PROJECT: '#A855F7',
  COMPANY: '#F97316',
  SCHOOL: '#06B6D4',
  POSITION: '#EC4899',
}

export const NODE_LABEL: Record<string, string> = {
  PERSON: '人物',
  SKILL: '技能',
  PROJECT: '项目',
  COMPANY: '公司',
  SCHOOL: '学校',
  POSITION: '职位',
}

export const TYPES = ['PERSON', 'SKILL', 'PROJECT', 'COMPANY', 'SCHOOL', 'POSITION'] as const

export function nodeColor(type: string): string {
  return NODE_COLOR[type] ?? '#94A3B8'
}

export function nodeLabel(type: string): string {
  return NODE_LABEL[type] ?? type
}

export type SimNode = d3.SimulationNodeDatum & KGNode & { degree?: number }
export type SimEdge = d3.SimulationLinkDatum<SimNode> & KGEdge & {
  pairTotal?: number
  pairIndex?: number
}

export interface RenderKGOptions {
  svg: SVGSVGElement
  nodes: KGNode[]
  edges: KGEdge[]
  layoutMode: 'force' | 'hierarchy'
  selectedId?: string | null
  onSelect?: (node: KGNode | null) => void
  showRelationLabels?: boolean
  markerId: string
}

export interface RenderKGHandle {
  zoomIn: () => void
  zoomOut: () => void
  fit: () => void
  stop: () => void
  /** 原地更新选中态，不重建模拟/视图 */
  setSelectedId: (id: string | null) => void
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

function pairKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`
}

function edgeGeometry(
  sx: number, sy: number,
  tx: number, ty: number,
  pairIndex: number,
  pairTotal: number,
): { path: string; mid: { x: number; y: number } } {
  const dx = tx - sx
  const dy = ty - sy
  const dist = Math.hypot(dx, dy) || 1
  const side = pairTotal > 1 ? (pairIndex % 2 === 0 ? 1 : -1) : 0
  const curvature = pairTotal > 1
    ? (0.14 + 0.04 * Math.floor(pairIndex / 2)) * side
    : 0.08
  const mx = (sx + tx) / 2
  const my = (sy + ty) / 2
  const nx = -dy / dist
  const ny = dx / dist
  const cx = mx + nx * dist * curvature
  const cy = my + ny * dist * curvature
  return {
    path: `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`,
    mid: {
      x: 0.25 * sx + 0.5 * cx + 0.25 * tx,
      y: 0.25 * sy + 0.5 * cy + 0.25 * ty,
    },
  }
}

export function renderKGGraph(opts: RenderKGOptions): RenderKGHandle {
  const {
    svg: svgEl,
    nodes: rawNodes,
    edges: rawEdges,
    layoutMode,
    selectedId: initialSelectedId,
    onSelect,
    showRelationLabels = true,
    markerId,
  } = opts

  const svg = d3.select(svgEl)
  svg.selectAll('*').remove()
  svg.on('click', null)

  const width = svgEl.clientWidth || 800
  const height = svgEl.clientHeight || 560

  const nodes: SimNode[] = rawNodes.map(n => ({ ...n }))
  const nodeById = new Map(nodes.map(n => [n.id, n]))
  const edges: SimEdge[] = rawEdges
    .filter(e => nodeById.has(String(e.source)) && nodeById.has(String(e.target)))
    .map(e => ({ ...e }))

  const degree = new Map<string, number>()
  const pairSeen = new Map<string, number>()
  const pairTotal = new Map<string, number>()
  const neighbors = new Map<string, Set<string>>()

  edges.forEach(e => {
    const s = String(e.source)
    const t = String(e.target)
    degree.set(s, (degree.get(s) ?? 0) + 1)
    degree.set(t, (degree.get(t) ?? 0) + 1)
    const k = pairKey(s, t)
    pairTotal.set(k, (pairTotal.get(k) ?? 0) + 1)
    if (!neighbors.has(s)) neighbors.set(s, new Set())
    if (!neighbors.has(t)) neighbors.set(t, new Set())
    neighbors.get(s)!.add(t)
    neighbors.get(t)!.add(s)
  })

  edges.forEach(e => {
    const s = String(e.source)
    const t = String(e.target)
    const k = pairKey(s, t)
    e.pairTotal = pairTotal.get(k) ?? 1
    e.pairIndex = pairSeen.get(k) ?? 0
    pairSeen.set(k, (pairSeen.get(k) ?? 0) + 1)
  })

  nodes.forEach(n => { n.degree = degree.get(n.id) ?? 0 })
  const maxDegree = Math.max(1, ...nodes.map(n => n.degree ?? 0))
  const radiusOf = (n: SimNode) => 16 + 10 * ((n.degree ?? 0) / maxDegree)

  const defs = svg.append('defs')

  const pattern = defs.append('pattern')
    .attr('id', `${markerId}-dots`)
    .attr('width', 24)
    .attr('height', 24)
    .attr('patternUnits', 'userSpaceOnUse')
  pattern.append('circle')
    .attr('cx', 1).attr('cy', 1).attr('r', 1)
    .attr('fill', '#94A3B8').attr('opacity', 0.16)

  Array.from(new Set(nodes.map(n => n.type))).forEach(type => {
    const c = nodeColor(type)
    const base = d3.color(c) ?? d3.color('#94A3B8')!
    const grad = defs.append('radialGradient')
      .attr('id', `${markerId}-grad-${type}`)
      .attr('cx', '35%').attr('cy', '30%').attr('r', '72%')
    grad.append('stop').attr('offset', '0%').attr('stop-color', base.brighter(0.55).formatHex())
    grad.append('stop').attr('offset', '100%').attr('stop-color', c)
  })

  defs.append('marker')
    .attr('id', markerId)
    .attr('viewBox', '0 -4 8 8')
    .attr('refX', 7)
    .attr('refY', 0)
    .attr('markerWidth', 7)
    .attr('markerHeight', 7)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-3.5L7,0L0,3.5')
    .attr('fill', '#94A3B8')
    .attr('opacity', 0.75)

  const filter = defs.append('filter')
    .attr('id', `${markerId}-shadow`)
    .attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%')
  filter.append('feDropShadow')
    .attr('dx', 0).attr('dy', 2).attr('stdDeviation', 3)
    .attr('flood-color', '#0F172A').attr('flood-opacity', 0.12)

  svg.append('rect')
    .attr('width', width)
    .attr('height', height)
    .attr('fill', `url(#${markerId}-dots)`)

  const root = svg.append('g').attr('class', 'kg-root')

  if (layoutMode === 'hierarchy') {
    const typeGroups = new Map<string, SimNode[]>()
    nodes.forEach(n => {
      if (!typeGroups.has(n.type)) typeGroups.set(n.type, [])
      typeGroups.get(n.type)!.push(n)
    })
    const typeOrder = [
      ...TYPES.filter(t => typeGroups.has(t)),
      ...Array.from(typeGroups.keys()).filter(t => !TYPES.includes(t as typeof TYPES[number])),
    ]
    const MIN_SPACING_X = 130
    const ROW_HEIGHT = 110
    const LAYER_GAP = 72
    const maxPerRow = Math.max(1, Math.floor((width - 48) / MIN_SPACING_X))

    let currentY = 64
    typeOrder.forEach(type => {
      const group = typeGroups.get(type)
      if (!group) return
      const rows = Math.ceil(group.length / maxPerRow)
      group.forEach((n, j) => {
        const row = Math.floor(j / maxPerRow)
        const col = j % maxPerRow
        const nodesInThisRow = Math.min(maxPerRow, group.length - row * maxPerRow)
        const rowWidth = nodesInThisRow * MIN_SPACING_X
        const startX = (width - rowWidth) / 2 + MIN_SPACING_X / 2
        n.x = startX + col * MIN_SPACING_X
        n.y = currentY + row * ROW_HEIGHT
        n.fx = n.x
        n.fy = n.y
      })
      currentY += rows * ROW_HEIGHT + LAYER_GAP
    })
  } else {
    // 力引导：大连通分量放中心，小分量紧贴周围，避免“团与团”被网格摊开
    const visited = new Set<string>()
    const components: SimNode[][] = []
    nodes.forEach(n => {
      if (visited.has(n.id)) return
      const stack = [n]
      const comp: SimNode[] = []
      visited.add(n.id)
      while (stack.length) {
        const cur = stack.pop()!
        comp.push(cur)
        neighbors.get(cur.id)?.forEach(id => {
          if (visited.has(id)) return
          visited.add(id)
          const next = nodeById.get(id)
          if (next) stack.push(next)
        })
      }
      components.push(comp)
    })
    components.sort((a, b) => b.length - a.length)

    const cx0 = width / 2
    const cy0 = height / 2 - 8
    // 团内半径按节点数估算，团与团之间留出明显空隙
    const packRadius = (size: number) => Math.max(40, 32 + Math.sqrt(size) * 22)
    const GAP = 96

    components.forEach((comp, i) => {
      const rIn = packRadius(comp.length)
      if (i === 0) {
        comp.forEach((n, j) => {
          const angle = (j / Math.max(comp.length, 1)) * Math.PI * 2
          const r = rIn * (0.4 + 0.55 * ((j % 5) / 5))
          n.x = cx0 + Math.cos(angle) * r
          n.y = cy0 + Math.sin(angle) * r
        })
        return
      }
      // 其余分量沿黄金角环绕主团，保持间距
      const angle = (i - 1) * 2.399963
      const dist = packRadius(components[0].length) + rIn + GAP
      const bx = cx0 + Math.cos(angle) * dist
      const by = cy0 + Math.sin(angle) * dist
      comp.forEach((n, j) => {
        const a = (j / Math.max(comp.length, 1)) * Math.PI * 2
        const r = rIn * (0.4 + 0.5 * ((j % 4) / 4))
        n.x = bx + Math.cos(a) * r
        n.y = by + Math.sin(a) * r
      })
    })
  }

  // 放宽布局：更长的边 + 更强斥力，节点不挤在一起
  const isForce = layoutMode === 'force'
  const sim = d3.forceSimulation<SimNode>(nodes)
    .force('link', d3.forceLink<SimNode, SimEdge>(edges)
      .id(d => d.id)
      .distance(d => {
        const s = d.source as SimNode
        const t = d.target as SimNode
        return 120 + (radiusOf(s) + radiusOf(t)) * 0.55
      })
      .strength(0.7))
    .force('charge', isForce
      ? d3.forceManyBody<SimNode>()
        .strength(d => -220 - (d.degree ?? 0) * 14)
        .distanceMax(360)
        .theta(0.9)
      : d3.forceManyBody<SimNode>().strength(0))
    .force('center', isForce ? d3.forceCenter(width / 2, height / 2 - 8).strength(0.06) : null)
    .force('collision', d3.forceCollide<SimNode>(d => radiusOf(d) + 22).iterations(2))
    .force('x', isForce ? d3.forceX<SimNode>(width / 2).strength(0.03) : null)
    .force('y', isForce ? d3.forceY<SimNode>(height / 2).strength(0.03) : null)
    .alphaDecay(0.035)
    .velocityDecay(0.4)

  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.15, 3.5])
    .on('zoom', (event) => {
      root.attr('transform', event.transform.toString())
    })
  svg.call(zoom)

  let currentSelectedId: string | null = initialSelectedId ?? null

  svg.on('click', (event) => {
    if (event.target === svgEl || (event.target as Element).classList?.contains('kg-bg')) {
      currentSelectedId = null
      applySelection()
      onSelect?.(null)
    }
  })

  // ── Edges ──────────────────────────────────────────────
  const linkG = root.append('g').attr('fill', 'none')
  const link = linkG.selectAll<SVGPathElement, SimEdge>('path')
    .data(edges, d => d.id)
    .join('path')
    .attr('stroke', '#94A3B8')
    .attr('stroke-opacity', 0.42)
    .attr('stroke-width', 1.35)
    .attr('stroke-linecap', 'round')
    .attr('marker-end', `url(#${markerId})`)

  const showLabels = showRelationLabels && edges.length <= 100
  let labels: d3.Selection<SVGTextElement, SimEdge, SVGGElement, unknown> | null = null
  let labelBg: d3.Selection<SVGRectElement, SimEdge, SVGGElement, unknown> | null = null

  if (showLabels) {
    const labelG = root.append('g').style('pointer-events', 'none')

    labelBg = labelG.selectAll<SVGRectElement, SimEdge>('rect')
      .data(edges, d => d.id)
      .join('rect')
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('fill', '#FFFFFF')
      .attr('fill-opacity', 0.9)
      .attr('stroke', '#E2E8F0')
      .attr('stroke-width', 0.6)
      .attr('height', 14)

    labels = labelG.selectAll<SVGTextElement, SimEdge>('text')
      .data(edges, d => d.id)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('font-size', 10)
      .attr('font-weight', 500)
      .attr('fill', '#64748B')
      .text(d => d.relation.length > 8 ? `${d.relation.slice(0, 8)}…` : d.relation)
  }

  // ── Nodes ──────────────────────────────────────────────
  const node = root.append('g')
    .selectAll<SVGGElement, SimNode>('g')
    .data(nodes, d => d.id)
    .join('g')
    .style('cursor', 'pointer')
    .call(
      d3.drag<SVGGElement, SimNode>()
        .on('start', (event, d) => {
          if (!event.active) sim.alphaTarget(0.2).restart()
          d.fx = event.x
          d.fy = event.y
        })
        .on('drag', (event, d) => {
          d.fx = event.x
          d.fy = event.y
        })
        .on('end', (event, d) => {
          if (!event.active) sim.alphaTarget(0)
          if (layoutMode !== 'hierarchy') {
            // 拖完短暂固定再放开，避免立刻被弹回
            d.fx = d.x
            d.fy = d.y
            window.setTimeout(() => {
              if (currentSelectedId !== d.id) {
                d.fx = null
                d.fy = null
              }
            }, 80)
          }
        }),
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      const nextId = currentSelectedId === d.id ? null : d.id
      currentSelectedId = nextId
      applySelection()
      if (!nextId) {
        onSelect?.(null)
        return
      }
      onSelect?.({
        id: d.id,
        label: d.label,
        type: d.type,
        attributes: d.attributes,
      })
    })

  node.append('circle')
    .attr('class', 'kg-select-ring')
    .attr('r', d => radiusOf(d) + 7)
    .attr('fill', 'none')
    .attr('stroke', 'transparent')
    .attr('stroke-width', 2)
    .attr('stroke-dasharray', '4 3')
    .attr('opacity', 0)

  node.append('circle')
    .attr('class', 'kg-glow')
    .attr('r', d => radiusOf(d) + 5)
    .attr('fill', d => hexToRgba(nodeColor(d.type), 0.14))
    .attr('opacity', 0)

  node.append('circle')
    .attr('class', 'kg-core')
    .attr('r', d => radiusOf(d))
    .attr('fill', d => `url(#${markerId}-grad-${d.type})`)
    .attr('stroke', '#FFFFFF')
    .attr('stroke-width', 2.4)
    .attr('filter', `url(#${markerId}-shadow)`)

  node.append('text')
    .attr('class', 'kg-label')
    .attr('text-anchor', 'middle')
    .attr('dy', '0.34em')
    .attr('font-size', d => Math.max(10, radiusOf(d) * 0.52))
    .attr('font-weight', 600)
    .attr('fill', '#0F172A')
    .attr('stroke', 'rgba(255,255,255,0.85)')
    .attr('stroke-width', 3)
    .attr('paint-order', 'stroke')
    .attr('pointer-events', 'none')
    .text(d => {
      const max = radiusOf(d) >= 22 ? 5 : 4
      return d.label.length > max ? `${d.label.slice(0, max)}…` : d.label
    })

  node.append('text')
    .attr('class', 'kg-type')
    .attr('text-anchor', 'middle')
    .attr('pointer-events', 'none')
    .attr('font-size', 9)
    .attr('font-weight', 600)
    .attr('fill', d => nodeColor(d.type))
    .attr('stroke', 'rgba(255,255,255,0.9)')
    .attr('stroke-width', 2.5)
    .attr('paint-order', 'stroke')
    .attr('dy', d => radiusOf(d) + 14)
    .text(d => nodeLabel(d.type))

  node
    .on('mouseenter', function () {
      d3.select(this).select('.kg-glow').transition().duration(160).attr('opacity', 1)
      d3.select(this).raise()
    })
    .on('mouseleave', function () {
      d3.select(this).select('.kg-glow').transition().duration(200).attr('opacity', 0)
    })

  function applySelection() {
    const sel = currentSelectedId
    const linked = new Set<string>()
    if (sel) {
      linked.add(sel)
      neighbors.get(sel)?.forEach(id => linked.add(id))
    }

    node.select('.kg-select-ring')
      .attr('stroke', d => (d.id === sel ? '#D97706' : 'transparent'))
      .attr('opacity', d => (d.id === sel ? 0.9 : 0))

    node.select('.kg-core')
      .attr('stroke', d => (d.id === sel ? '#D97706' : '#FFFFFF'))
      .attr('stroke-width', d => (d.id === sel ? 3.2 : 2.4))

    node.select('.kg-label')
      .attr('fill', d => {
        if (!sel) return '#0F172A'
        if (d.id === sel) return '#92400E'
        if (linked.has(d.id)) return '#0F172A'
        return '#94A3B8'
      })

    node.style('opacity', d => {
      if (!sel) return 1
      return linked.has(d.id) ? 1 : 0.28
    })

    link
      .attr('stroke', d => {
        if (!sel) return '#94A3B8'
        const s = String(d.source)
        const t = String(d.target)
        return s === sel || t === sel ? '#D97706' : '#CBD5E1'
      })
      .attr('stroke-opacity', d => {
        if (!sel) return 0.42
        const s = String(d.source)
        const t = String(d.target)
        return s === sel || t === sel ? 0.85 : 0.12
      })
      .attr('stroke-width', d => {
        if (!sel) return 1.35
        const s = String(d.source)
        const t = String(d.target)
        return s === sel || t === sel ? 2 : 1.1
      })

    if (labels && labelBg) {
      labels.attr('fill', d => {
        if (!sel) return '#64748B'
        const s = String(d.source)
        const t = String(d.target)
        return s === sel || t === sel ? '#92400E' : '#CBD5E1'
      })
      labelBg.attr('fill-opacity', d => {
        if (!sel) return 0.9
        const s = String(d.source)
        const t = String(d.target)
        return s === sel || t === sel ? 0.95 : 0.35
      })
    }
  }

  applySelection()

  type XY = { x: number; y: number }
  const asXY = (v: SimEdge['source'] | SimEdge['target']): XY => v as unknown as XY

  function edgeEndpoints(d: SimEdge) {
    const s = asXY(d.source)
    const t = asXY(d.target)
    const sn = d.source as SimNode
    const tn = d.target as SimNode
    const rs = radiusOf(sn)
    const rt = radiusOf(tn)
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dist = Math.hypot(dx, dy) || 1
    return {
      sx: s.x + (dx / dist) * rs,
      sy: s.y + (dy / dist) * rs,
      tx: t.x - (dx / dist) * (rt + 2),
      ty: t.y - (dy / dist) * (rt + 2),
      pairIndex: d.pairIndex ?? 0,
      pairTotal: d.pairTotal ?? 1,
    }
  }

  sim.on('tick', () => {
    link.attr('d', d => {
      const e = edgeEndpoints(d)
      return edgeGeometry(e.sx, e.sy, e.tx, e.ty, e.pairIndex, e.pairTotal).path
    })

    if (labels && labelBg) {
      labels
        .attr('x', d => {
          const e = edgeEndpoints(d)
          return edgeGeometry(e.sx, e.sy, e.tx, e.ty, e.pairIndex, e.pairTotal).mid.x
        })
        .attr('y', d => {
          const e = edgeEndpoints(d)
          return edgeGeometry(e.sx, e.sy, e.tx, e.ty, e.pairIndex, e.pairTotal).mid.y
        })

      labelBg
        .attr('x', function (d, i) {
          const tw = labels!.nodes()[i]?.getComputedTextLength() ?? d.relation.length * 6
          return Number(d3.select(labels!.nodes()[i]).attr('x') ?? 0) - (tw + 10) / 2
        })
        .attr('y', function (d, i) {
          return Number(d3.select(labels!.nodes()[i]).attr('y') ?? 0) - 7
        })
        .attr('width', function (d, i) {
          const tw = labels!.nodes()[i]?.getComputedTextLength() ?? d.relation.length * 6
          return tw + 10
        })
    }

    node.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`)
  })

  sim.alpha(0.7).restart()

  return {
    zoomIn: () => { svg.transition().duration(220).call(zoom.scaleBy, 1.3) },
    zoomOut: () => { svg.transition().duration(220).call(zoom.scaleBy, 1 / 1.3) },
    fit: () => {
      if (!nodes.length) {
        svg.transition().duration(280).call(zoom.transform, d3.zoomIdentity)
        return
      }
      const xs = nodes.map(n => n.x ?? width / 2)
      const ys = nodes.map(n => n.y ?? height / 2)
      const minX = Math.min(...xs) - 50
      const maxX = Math.max(...xs) + 50
      const minY = Math.min(...ys) - 50
      const maxY = Math.max(...ys) + 50
      const bw = Math.max(maxX - minX, 1)
      const bh = Math.max(maxY - minY, 1)
      const scale = Math.min(width / bw, height / bh, 1.4)
      const tx = width / 2 - scale * ((minX + maxX) / 2)
      const ty = height / 2 - scale * ((minY + maxY) / 2)
      svg.transition().duration(360).call(
        zoom.transform,
        d3.zoomIdentity.translate(tx, ty).scale(scale),
      )
    },
    stop: () => { sim.stop() },
    setSelectedId: (id: string | null) => {
      currentSelectedId = id
      applySelection()
    },
  }
}
