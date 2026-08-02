import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Send, Square, ThumbsUp, ThumbsDown, ChevronDown, ChevronUp, Zap, Share2, Paperclip } from 'lucide-react'
import { docApi, qaApi } from '@/services/api'
import { useSSE } from '@/hooks/useSSE'
import { useToast } from '@/hooks/useToast'
import type { QAMessage, QASource, RetrievalMode } from '@/types'
import { clsx } from 'clsx'

function SourcePanel({ sources }: { sources: QASource[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3 border border-border rounded-xl overflow-hidden bg-[#FEF9C3]/40">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-3.5 py-2.5 text-xs font-semibold text-warning hover:bg-amber-50/50 transition-colors">
        <div className="flex items-center gap-1.5">
          <span>📚</span> 引用来源 ({sources.length} 处)
        </div>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {open && (
        <div className="border-t border-border divide-y divide-border">
          {sources.map((s, i) => (
            <div key={i} className="px-3.5 py-2.5 bg-surface">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold text-tp">{s.doc_name} · 第 {s.page} 页</span>
                <button className="text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded-md hover:bg-primary/20">定位</button>
              </div>
              <p className="text-[11px] text-ts italic">"{s.excerpt}"</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MessageBubble({ msg, onFeedback }: { msg: QAMessage & { streaming?: boolean }; onFeedback?: (rating: 'up' | 'down') => void }) {
  const [rated, setRated] = useState<'up' | 'down' | null>(null)

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[65%] bg-primary text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed">
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5">AI</div>
      <div className="flex-1 min-w-0">
        {msg.streaming && !msg.content ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => <div key={i} className="h-4 rounded skeleton" style={{ width: `${80 - i * 15}%` }} />)}
          </div>
        ) : (
          <div className="bg-surface border border-border rounded-2xl rounded-tl-sm px-4 py-3">
            <div className={clsx('text-sm text-tp leading-relaxed whitespace-pre-wrap', msg.streaming && 'streaming-cursor')}
              dangerouslySetInnerHTML={{ __html: msg.content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>') }} />
            {msg.sources && msg.sources.length > 0 && <SourcePanel sources={msg.sources} />}
            {!msg.streaming && msg.query_id && (
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                <div className="flex items-center gap-2">
                  {(['up', 'down'] as const).map((r) => (
                    <button key={r} disabled={!!rated} onClick={() => { setRated(r); onFeedback?.(r) }}
                      className={clsx(
                        'flex items-center gap-1 h-7 px-2.5 rounded-full text-xs border transition-colors',
                        rated === r
                          ? r === 'up' ? 'bg-green-100 border-success text-success' : 'bg-orange-100 border-warning text-warning'
                          : 'border-border text-ts hover:bg-bg'
                      )}>
                      {r === 'up' ? <><ThumbsUp size={11} /> 有帮助</> : <><ThumbsDown size={11} /> 需改进</>}
                    </button>
                  ))}
                </div>
                {msg.tokens && (
                  <div className="flex items-center gap-1 text-[10px] text-ts">
                    <Zap size={10} /> {msg.tokens.input + msg.tokens.output} tokens
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function SingleDocQAPage() {
  const { kbId, docId } = useParams<{ kbId: string; docId: string }>()
  const navigate = useNavigate()
  const toast = useToast()
  const { connect } = useSSE()
  const stopRef = useRef<(() => void) | null>(null)

  const [messages, setMessages] = useState<(QAMessage & { streaming?: boolean })[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [mode, setMode] = useState<RetrievalMode>('kg_only')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: doc } = useQuery({ queryKey: ['doc', docId], queryFn: async () => {
    const docs = await docApi.list(kbId!)
    return docs.find(d => d.doc_id === docId)
  }, enabled: !!kbId && !!docId })

  const feedbackMut = useMutation({ mutationFn: ({ qid, r }: { qid: string; r: 'up' | 'down' }) => qaApi.feedback(qid, { rating: r }) })

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const send = useCallback(() => {
    const q = input.trim()
    if (!q || isStreaming) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setIsStreaming(true)

    const aiMsg: QAMessage & { streaming: boolean } = { role: 'assistant', content: '', streaming: true }
    setMessages(prev => [...prev, aiMsg])

    const stop = connect(
      '/api/v1/qa/query',
      { doc_id: docId, question: q, retrieval_mode: mode, stream: true },
      {
        onDelta: (chunk) => setMessages(prev => {
          const arr = [...prev]
          arr[arr.length - 1] = { ...arr[arr.length - 1], content: arr[arr.length - 1].content + chunk }
          return arr
        }),
        onDone: (meta) => {
          setMessages(prev => {
            const arr = [...prev]
            arr[arr.length - 1] = {
              ...arr[arr.length - 1],
              streaming: false,
              query_id: meta.query_id,
              tokens: meta.tokens,
              sources: meta.sources as QASource[] | undefined,
              finish_reason: meta.finish_reason,
            }
            return arr
          })
          setIsStreaming(false)
        },
        onError: (msg) => {
          setMessages(prev => {
            const arr = [...prev]
            arr[arr.length - 1] = { ...arr[arr.length - 1], content: `❌ ${msg}`, streaming: false }
            return arr
          })
          setIsStreaming(false)
          toast.error(msg)
        },
      }
    )
    if (stop) stopRef.current = stop
  }, [input, isStreaming, docId, mode, connect, toast])

  const stopStream = () => { stopRef.current?.(); setIsStreaming(false); setMessages(prev => { const a = [...prev]; a[a.length-1] = { ...a[a.length-1], streaming: false }; return a }) }

  return (
    <div className="h-full flex flex-col">
      {/* Doc info bar */}
      <div className="h-[54px] bg-surface border-b border-border flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(`/kb/${kbId}`)} className="text-ts hover:text-tp">
            <Share2 size={16} />
          </button>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-tp">{doc?.original_name ?? '文档问答'}</span>
            <span className="text-xs bg-green-100 text-success px-2 py-0.5 rounded-full font-semibold">已索引</span>
            {doc && <span className="text-xs text-ts">{doc.node_count} 节点 · {doc.edge_count} 关系</span>}
          </div>
        </div>
        {/* Mode switch */}
        <div className="flex items-center gap-1 p-1 bg-bg border border-border rounded-lg">
          {(['kg_only', 'hybrid'] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={clsx('h-7 px-3 rounded-md text-xs font-medium transition-colors', mode === m ? 'bg-primary text-white' : 'text-ts hover:text-tp')}>
              {m === 'kg_only' ? 'KG-Only 模式' : '混合检索'}
            </button>
          ))}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
              <span className="text-3xl">💬</span>
            </div>
            <h3 className="text-base font-semibold text-tp mb-2">开始智能问答</h3>
            <p className="text-sm text-ts max-w-xs mb-6">基于知识图谱，快速找到文档中的关键信息</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-md">
              {['文档的核心技能有哪些？', '主要工作经历是什么？', '擅长哪些技术框架？'].map(q => (
                <button key={q} onClick={() => setInput(q)} className="text-xs text-primary bg-primary/10 border border-primary/20 px-3 py-1.5 rounded-full hover:bg-primary/20">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} onFeedback={(r) => msg.query_id && feedbackMut.mutate({ qid: msg.query_id, r })} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 pb-5 pt-3 bg-surface border-t border-border">
        <div className={clsx('border-2 rounded-xl overflow-hidden', isStreaming ? 'border-primary' : 'border-border focus-within:border-primary')} >
          <textarea
            value={input} onChange={e => setInput(e.target.value)} rows={2}
            onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send() } }}
            placeholder="输入问题... (Ctrl+Enter 发送)"
            className="w-full px-4 pt-3 pb-1 text-sm text-tp resize-none outline-none bg-transparent"
          />
          <div className="flex items-center justify-between px-3 pb-2">
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-bg text-ts">
                <Paperclip size={13} />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-ts">{mode === 'kg_only' ? 'KG-Only 模式' : '混合检索模式'}</span>
              {isStreaming ? (
                <button onClick={stopStream} className="flex items-center gap-1.5 h-8 px-3.5 bg-slate-900 text-white rounded-lg text-xs font-semibold">
                  <Square size={11} /> 停止
                </button>
              ) : (
                <button onClick={send} disabled={!input.trim()}
                  className="flex items-center gap-1.5 h-8 px-3.5 bg-primary text-white rounded-lg text-xs font-semibold hover:bg-primary-hover disabled:opacity-40">
                  <Send size={13} /> 发送
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
