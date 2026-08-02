// ───────────────────────── 通用 ─────────────────────────
export type DocStatus = 'uploaded' | 'indexing' | 'indexed' | 'failed'
export type RetrievalMode = 'kg_only' | 'hybrid'

// ───────────────────────── 用户 / Auth ─────────────────────────
export interface User {
  user_id: string
  email: string
  username: string
  created_at?: string
}

export interface AuthResponse {
  access_token: string
  user: User
}

// ───────────────────────── 知识库 ─────────────────────────
export interface KnowledgeBase {
  kb_id: string
  name: string
  description: string
  color: string
  owner_id: string
  doc_count: number
  indexed_count: number
  total_nodes: number
  total_edges: number
  created_at: string
  updated_at: string
}

export interface KBCreatePayload {
  name: string
  description: string
  color: string
}

// ───────────────────────── 文档 ─────────────────────────
export interface Document {
  doc_id: string
  kb_id: string
  filename: string
  original_name: string
  file_format: string
  status: DocStatus
  node_count: number
  edge_count: number
  page_count: number
  file_size: number
  created_at: string
  updated_at: string
  error_message?: string
}

export interface IndexTask {
  task_id: string
  doc_id: string
  status: DocStatus
  progress: number
  current_stage: number
  stages: IndexStage[]
  created_at: string
  updated_at: string
}

export interface IndexStage {
  name: string
  label: string
  status: 'pending' | 'running' | 'done' | 'failed'
  progress: number
}

// ───────────────────────── 知识图谱 ─────────────────────────
export interface KGNode {
  id: string
  label: string
  type: string
  attributes: Record<string, unknown>
}

export interface KGEdge {
  id: string
  source: string
  target: string
  relation: string
}

export interface KGGraph {
  doc_id: string
  nodes: KGNode[]
  edges: KGEdge[]
  meta: { total_nodes: number; total_edges: number }
}

// ───────────────────────── 问答 ─────────────────────────
export interface QAMessage {
  role: 'user' | 'assistant'
  content: string
  query_id?: string
  sources?: QASource[]
  tokens?: { input: number; output: number }
  finish_reason?: string
  created_at?: string
}

export interface QASource {
  doc_id: string
  doc_name: string
  page: number
  excerpt: string
}

export interface FeedbackPayload {
  // UI uses 'up'/'down'; api.ts maps to backend's 'positive'/'negative'
  rating: 'up' | 'down'
  comment?: string
}

// ───────────────────────── KG 编辑操作 ─────────────────────────
export type KGOperation =
  | { op: 'add_node'; node: KGNode }
  | { op: 'update_node'; node_id: string; patch: Partial<Omit<KGNode, 'id'>> }
  | { op: 'delete_node'; node_id: string }
  | { op: 'add_edge'; edge: KGEdge }
  | { op: 'update_edge'; edge_id: string; patch: Partial<Omit<KGEdge, 'id'>> }
  | { op: 'delete_edge'; edge_id: string }

// ───────────────────────── Webhook ─────────────────────────
export interface Webhook {
  webhook_id: string
  url: string
  events: string[]
  is_active: boolean
  created_at: string
}

export interface WebhookCreatePayload {
  url: string
  events: string[]
  secret?: string
}

// ───────────────────────── 问答历史 ─────────────────────────
export interface QAHistory {
  query_id: string
  question: string
  answer: string
  doc_id?: string
  kb_id?: string
  retrieval_mode: RetrievalMode
  input_tokens: number
  output_tokens: number
  created_at: string
}
