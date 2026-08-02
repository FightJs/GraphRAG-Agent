import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type {
  AuthResponse, User, KnowledgeBase, KBCreatePayload,
  Document, IndexTask, KGGraph, KGOperation, QAHistory, FeedbackPayload,
  Webhook, WebhookCreatePayload,
} from '@/types'

const http = axios.create({ baseURL: '/api', timeout: 30_000 })

http.interceptors.request.use((cfg) => {
  const token = useAuthStore.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(
  (res) => res,
  async (err) => {
    const orig = err.config
    if (err.response?.status === 401 && !orig._retry) {
      orig._retry = true
      try {
        // refresh_token is in httponly cookie, sent automatically
        const { data } = await axios.post<{ data: { access_token: string } }>('/api/v2/auth/refresh')
        const token = data.data.access_token
        useAuthStore.getState().setToken(token)
        orig.headers.Authorization = `Bearer ${token}`
        return http(orig)
      } catch {
        useAuthStore.getState().logout()
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

// All backend responses are wrapped: { code, msg, data, trace_id }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const d = <T>(r: { data: { data: T } }): T => r.data.data

// ── Auth ──────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    http.post<{ data: AuthResponse }>('/v2/auth/login', { email, password }).then(d<AuthResponse>),

  // register returns user info only (no token); caller must login afterwards
  register: (email: string, password: string, username: string) =>
    http.post<{ data: User }>('/v2/auth/register', { email, password, username }).then(d<User>),

  // best-effort: invalidates refresh token on server (clears httpOnly cookie)
  logout: () => http.post('/v2/auth/logout').catch(() => {}),
}

// ── Knowledge Base ────────────────────────────────────────────
export const kbApi = {
  list: () =>
    http.get<{ data: { items: KnowledgeBase[]; total: number } }>('/v2/kbs')
      .then(r => d<{ items: KnowledgeBase[]; total: number }>(r).items),
  get: (id: string) =>
    http.get<{ data: KnowledgeBase }>(`/v2/kbs/${id}`).then(d<KnowledgeBase>),
  create: (p: KBCreatePayload) =>
    http.post<{ data: KnowledgeBase }>('/v2/kbs', p).then(d<KnowledgeBase>),
  update: (id: string, p: Partial<KBCreatePayload>) =>
    http.patch<{ data: KnowledgeBase }>(`/v2/kbs/${id}`, p).then(d<KnowledgeBase>),
  delete: (id: string) => http.delete(`/v2/kbs/${id}`),
}

// ── Documents ─────────────────────────────────────────────────
export const docApi = {
  list: (kbId: string) =>
    http.get<{ data: Document[] }>(`/v1/documents?kb_id=${kbId}`).then(d<Document[]>),

  upload: (kbId: string, file: File, onProgress?: (pct: number) => void) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('kb_id', kbId)
    return http.post<{ data: Document }>('/v1/documents/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded * 100) / e.total)),
    }).then(d<Document>)
  },

  batchUpload: (kbId: string, files: File[], onProgress?: (pct: number) => void) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files[]', f))
    fd.append('kb_id', kbId)
    return http.post<{ data: { uploaded: { doc_id: string; filename: string; status: string }[]; failed: { filename: string; error: string }[] } }>(
      '/v2/documents/batch-upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded * 100) / e.total)),
      }
    ).then(d<{ uploaded: { doc_id: string; filename: string; status: string }[]; failed: { filename: string; error: string }[] }>)
  },

  delete: (docId: string) => http.delete(`/v1/documents/${docId}`),

  startIndex: (docId: string, opts?: { page_start?: number; page_end?: number }) =>
    http.post<{ data: IndexTask }>(`/v1/documents/${docId}/index`, opts).then(d<IndexTask>),

  getTask: (taskId: string) =>
    http.get<{ data: IndexTask }>(`/v1/index/tasks/${taskId}`).then(d<IndexTask>),
}

// ── Knowledge Graph ───────────────────────────────────────────
export const kgApi = {
  get: (docId: string) =>
    http.get<{ data: KGGraph }>(`/v1/kg/${docId}`).then(d<KGGraph>),

  // v2: send diff operations list, NOT the full graph
  save: (docId: string, operations: KGOperation[]) =>
    http.patch(`/v2/kg/${docId}`, { operations }).then(r => r.data),
}

// ── Q&A ──────────────────────────────────────────────────────
export const qaApi = {
  history: (params?: { kb_id?: string; doc_id?: string }) =>
    http.get<{ data: QAHistory[] }>('/v1/qa/history', { params }).then(d<QAHistory[]>),

  // Maps UI 'up'/'down' → backend 'positive'/'negative'
  feedback: (queryId: string, p: FeedbackPayload) =>
    http.post(`/v2/qa/${queryId}/feedback`, {
      rating: p.rating === 'up' ? 'positive' : 'negative',
      comment: p.comment,
    }).then(r => r.data),
}

// ── Webhooks ─────────────────────────────────────────────────
export const webhookApi = {
  list: () =>
    http.get<{ data: Webhook[] }>('/v2/webhooks').then(d<Webhook[]>),
  create: (p: WebhookCreatePayload) =>
    http.post<{ data: Webhook }>('/v2/webhooks', p).then(d<Webhook>),
  update: (id: string, p: Partial<WebhookCreatePayload>) =>
    http.patch<{ data: Webhook }>(`/v2/webhooks/${id}`, p).then(d<Webhook>),
  delete: (id: string) => http.delete(`/v2/webhooks/${id}`),
}

export default http
