import { useCallback, useRef } from 'react'
import { useAuthStore } from '@/stores/authStore'

interface SSEOptions {
  onDelta: (content: string) => void
  onDone: (meta: { query_id: string; tokens: { input: number; output: number }; finish_reason: string; sources?: unknown[] }) => void
  onError: (msg: string) => void
}

export function useSSE() {
  const esRef = useRef<EventSource | null>(null)

  const connect = useCallback((url: string, body: Record<string, unknown>, opts: SSEOptions) => {
    esRef.current?.close()
    const token = useAuthStore.getState().token

    // Use fetch for POST + SSE
    const ctrl = new AbortController()
    fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    }).then(async (res) => {
      if (!res.ok) { opts.onError(`请求失败 (${res.status})`); return }
      const reader = res.body?.getReader()
      if (!reader) return
      const dec = new TextDecoder()
      let buf = ''
      let currentEvent = 'message'
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
            continue
          }
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const ev = JSON.parse(raw)
            if (currentEvent === 'delta') opts.onDelta(ev.content ?? '')
            else if (currentEvent === 'done') opts.onDone({
              query_id: ev.query_id,
              tokens: { input: ev.token_usage?.input_tokens ?? 0, output: ev.token_usage?.output_tokens ?? 0 },
              finish_reason: ev.finish_reason,
              sources: ev.sources,
            })
            else if (currentEvent === 'error') opts.onError(ev.msg ?? '未知错误')
          } catch { /* skip malformed */ }
        }
      }
    }).catch((e) => { if (e.name !== 'AbortError') opts.onError(e.message) })

    return () => ctrl.abort()
  }, [])

  const stop = useCallback(() => esRef.current?.close(), [])

  return { connect, stop }
}
