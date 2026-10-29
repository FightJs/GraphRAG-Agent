import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildGraphIndex, buildVisibleGraph } from '../src/components/kg/graphModel'
import type { KGGraph } from '../src/types'

function fixture(): KGGraph {
  const nodes = [{ id: 'hero', label: '主角', type: 'PERSON', attributes: {} }, { id: 'shared', label: '共享', type: 'OTHER', attributes: {} }, { id: 'other', label: '另一个', type: 'PERSON', attributes: {} }, ...Array.from({ length: 15 }, (_, i) => ({ id: `leaf${i}`, label: `物品${i}`, type: 'OTHER', attributes: {} }))]
  const edges = [ ...Array.from({ length: 15 }, (_, i) => ({ id: `edge${i}`, source: 'hero', target: `leaf${i}`, relation: i % 2 ? '购买' : '购买了' })), { id: 's1', source: 'hero', target: 'shared', relation: '购买' }, { id: 's2', source: 'other', target: 'shared', relation: '认识' } ]
  return { doc_id: 'test', nodes, edges, meta: { total_nodes: nodes.length, total_edges: edges.length } }
}
const opts = { mode: 'overview' as const, selectedId: null, expanded: new Map<string, number>(), pinned: new Set<string>(), revealed: new Set<string>(), types: new Set<string>() }
test('group only repeated single-neighbor leaves; original graph remains untouched', () => {
 const graph = fixture(); const original = JSON.stringify(graph); const index = buildGraphIndex(graph)
 assert.equal(index.groups.length, 1); assert.equal(index.groups[0].nodes.length, 15); assert(!index.groupedIds.has('shared'))
 const view = buildVisibleGraph(graph, index, opts)
 assert.equal(view.realCount, 3); assert.equal(view.groups.length, 1); assert.equal(JSON.stringify(graph), original)
})
test('expand in batches, collapse retains explicitly revealed nodes, and full view has original edges', () => {
 const graph = fixture(); const index = buildGraphIndex(graph); const group = index.groups[0]
 const expanded = buildVisibleGraph(graph, index, { ...opts, expanded: new Map([[group.id, 12]]) })
 assert.equal(expanded.realCount, 15); assert.equal(expanded.groups.length, 1)
 const collapsed = buildVisibleGraph(graph, index, { ...opts, revealed: new Set(['leaf0']) })
 assert(collapsed.nodes.some(n => n.id === 'leaf0')); assert.equal(collapsed.realCount, 4)
 const all = buildVisibleGraph(graph, index, { ...opts, mode: 'all' })
 assert.equal(all.realCount, graph.nodes.length); assert.equal(all.edges.length, graph.edges.length); assert.equal(all.groups.length, 0)
})
test('empty graphs and filters remain safe', () => {
 const graph: KGGraph = { doc_id: 'empty', nodes: [], edges: [], meta: { total_nodes: 0, total_edges: 0 } }
 assert.equal(buildVisibleGraph(graph, buildGraphIndex(graph), opts).nodes.length, 0)
 const populated = fixture(); const view = buildVisibleGraph(populated, buildGraphIndex(populated), { ...opts, types: new Set(['PERSON']) })
 assert(view.nodes.every(n => n.type === 'PERSON'))
})
