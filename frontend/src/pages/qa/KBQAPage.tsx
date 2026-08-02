import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Send, Square, ThumbsUp, ThumbsDown, ChevronDown, ChevronUp, Files, Zap, Search } from 'lucide-react'
import { docApi, qaApi } from '@/services/api'
import { useSSE } from '@/hooks/useSSE'
import { useToast } from '@/hooks/useToast'
import type { Document, QAMessage, QASource, RetrievalMode } from '@/types'
import { clsx } from 'clsx'

function SourceItem({ src, idx }: { src: QASource; idx: number }) {
  return (
    <div className="flex items-start gap-3 px-3.5 py-2.5 bg-surface border-t border-border">
      <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0 mt-0.5">
        {idx + 1}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-semibold text-tp">{src.doc_name} · 第 {src.page} 页</span>
          <button className="text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded-md hover:bg-primary/20 flex-shrink-0">定位</button>
        </div>
        <p className="text-[11px] text-ts italic">"{src.excerpt}"</p>
      </div>
    </div>
  )
}

function AIMsgBubble({ msg, onFeedback }: { msg: QAMessage & { streaming?: boolean }; onFeedback?: (r: 'up' | 'down') => void }) {
  const [srcOpen, setSrcOpen] = useState(false)
  const [rated, setRated] = useState<'up' | 'down' | null>(null)
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[65%] bg-primary text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed whitespace-pre-wrap">
          {msg.content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5">AI</div>
      <div className="flex-1 min-w-0 bg-surface border border-border rounded-2xl rounded-tl-sm">
        {msg.streaming && !msg.content ? (
          <div className="p-4 space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-4 rounded skeleton" style={{ width: `${80 - i * 15}%` }} />)}</div>
        ) : (
          <>
            <div className={clsx('px-4 py-3 text-sm text-tp leading-relaxed whitespace-pre-wrap', msg.streaming && 'streaming-cursor')}
              dangerouslySetInnerHTML={{ __html: msg.content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>') }} />
            {msg.sources && msg.sources.length > 0 && (
              <div className="border-t border-[#FEF9C3] bg-[#FEF9C3]/50">
                <button onClick={() => setSrcOpen(!srcOpen)} className="w-full flex items-center justify-between px-3.5 py-2.5 text-xs font-semibold text-warning">
                  <div className="flex items-center gap-1.5">
                    <span>📚</span> 引用来源 ({msg.sources.length} 处)
                  </div>
                  {srcOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {srcOpen && msg.sources.map((s, i) => <SourceItem key={i} src={s} idx={i} />)}
              </div>
            )}
            {!msg.streaming && msg.query_id && (
              <div className="flex items-center justify-between px-4 py-2.5 border-t border-border">
                <div className="flex items-center gap-2">
                  {(['up', 'down'] as const).map((r) => (
                    <button key={r} disabled={!!rated} onClick={() => { setRated(r); onFeedback?.(r) }}
                      className={clsx('flex items-center gap-1 h-7 px-2.5 rounded-full text-xs border transition-colors',
                        rated === r ? (r === 'up' ? 'bg-green-100 border-success text-success' : 'bg-orange-100 border-warning text-warning') : 'border-border text-ts hover:bg-bg')}>
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
          </>
        )}
      </div>
    </div>
  )
}

export default function KBQAPage() {
  const { kbId } = useParams<{ kbId: string }>()
  const toast = useToast()
  const { connect } = useSSE()
  const stopRef = useRef<(() => void) | null>(null)

  const [messages, setMessages] = useState<(QAMessage & { streaming?: boolean })[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [mode, setMode] = useState<RetrievalMode>('hybrid')
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set())
  const [docSearch, setDocSearch] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: docs = [] } = useQuery({
    queryKey: ['docs', kbId],
    queryFn: () => docApi.list(kbId!),
    enabled: !!kbId,
  })

  const indexedDocs = docs.filter(d => d.status === 'indexed')
  const feedbackMut = useMutation({ mutationFn: ({ qid, r }: { qid: string; r: 'up' | 'down' }) => qaApi.feedback(qid, { rating: r }) })

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const toggleDoc = (id: string) => {
    setSelectedDocs(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) }
      else if (next.size >= 10) { toast.warning('最多同时选 10 份文档参与检索'); return prev }
      else { next.add(id) }
      return next
    })
  }

  const toggleAll = () => {
    if (selectedDocs.size === indexedDocs.length) setSelectedDocs(new Set())
    else setSelectedDocs(new Set(indexedDocs.map(d => d.doc_id)))
  }

  const send = useCallback(() => {
    const q = input.trim()
    if (!q || isStreaming || selectedDocs.size === 0) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setIsStreaming(true)
    const aiMsg: QAMessage & { streaming: boolean } = { role: 'assistant', content: '', streaming: true }
    setMessages(prev => [...prev, aiMsg])

    const stop = connect(
      '/api/v2/qa/kb-query',
      { kb_id: kbId, doc_ids: Array.from(selectedDocs), question: q, retrieval_mode: mode, stream: true },
      {
        onDelta: (chunk) => setMessages(prev => { const a = [...prev]; a[a.length-1] = { ...a[a.length-1], content: a[a.length-1].content + chunk }; return a }),
        onDone: (meta) => {
          setMessages(prev => { const a = [...prev]; a[a.length-1] = { ...a[a.length-1], streaming: false, query_id: meta.query_id, tokens: meta.tokens, sources: meta.sources as QASource[] | undefined }; return a })
          setIsStreaming(false)
        },
        onError: (msg) => {
          setMessages(prev => { const a = [...prev]; a[a.length-1] = { ...a[a.length-1], content: `❌ ${msg}`, streaming: false }; return a })
          setIsStreaming(false)
          toast.error(msg)
        },
      }
    )
    if (stop) stopRef.current = stop
  }, [input, isStreaming, selectedDocs, kbId, mode, connect, toast])

  const filteredDocs = indexedDocs.filter(d => d.original_name.toLowerCase().includes(docSearch.toLowerCase()))

  return (
    <div className="h-full flex overflow-hidden">
      {/* Left doc select panel */}
      <div className="w-[260px] border-r border-border bg-surface flex-shrink-0 flex flex-col">
        <div className="border-b border-border">
          <div className="flex items-center justify-between px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-tp">选择参与问答的文档</p>
              <p className="text-xs text-primary mt-0.5">已选 {selectedDocs.size} / {Math.min(indexedDocs.length, 10)} 份</p>
            </div>
            <button onClick={toggleAll} className="text-xs text-primary bg-primary/10 px-2.5 py-1 rounded-md font-semibold hover:bg-primary/20">
              {selectedDocs.size === indexedDocs.length ? '取消' : '全选'}
            </button>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 border-t border-border">
            <Search size={13} className="text-ts" />
            <input value={docSearch} onChange={e => setDocSearch(e.target.value)} placeholder="搜索文档..." className="flex-1 text-xs outline-none bg-transparent" />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {docs.filter(d => d.original_name.toLowerCase().includes(docSearch.toLowerCase())).map((doc: Document) => {
            const isIndexed = doc.status === 'indexed'
            const isSelected = selectedDocs.has(doc.doc_id)
            return (
              <label key={doc.doc_id} className={clsx('flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors', isIndexed ? (isSelected ? 'bg-primary/5' : 'hover:bg-bg') : 'opacity-40 cursor-not-allowed')}>
                <input type="checkbox" disabled={!isIndexed} checked={isSelected} onChange={() => isIndexed && toggleDoc(doc.doc_id)}
                  className="w-4 h-4 rounded border-border text-primary accent-primary" />
                <div className="flex-1 min-w-0">
                  <p className={clsx('text-xs font-medium truncate', isSelected ? 'text-primary' : 'text-tp')}>{doc.original_name}</p>
                  <p className="text-[10px] text-ts">{isIndexed ? `${doc.node_count} 节点` : doc.status === 'indexing' ? '索引中...' : '未索引'}</p>
                </div>
              </label>
            )
          })}
          {filteredDocs.length === 0 && (
            <p className="text-xs text-ts text-center py-6">暂无已索引文档</p>
          )}
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <div className="h-[54px] bg-surface border-b border-border flex items-center justify-between px-6 flex-shrink-0">
          <div>
            <p className="text-sm font-semibold text-tp">知识库联合问答</p>
            {selectedDocs.size > 0 && (
              <div className="flex items-center gap-1 text-xs text-ts">
                <Files size={11} />
                已选 {selectedDocs.size} 份文档参与检索
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 p-1 bg-bg border border-border rounded-lg">
            {(['kg_only', 'hybrid'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={clsx('h-7 px-3 rounded-md text-xs font-medium transition-colors', mode === m ? 'bg-primary text-white' : 'text-ts hover:text-tp')}>
                {m === 'kg_only' ? 'KG-Only' : '混合检索模式'}
              </button>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4 text-3xl">🔍</div>
              <h3 className="text-base font-semibold text-tp mb-2">跨文档联合问答</h3>
              <p className="text-sm text-ts max-w-xs mb-2">
                {selectedDocs.size === 0
                  ? '请先在左侧选择要参与检索的文档'
                  : `已选 ${selectedDocs.size} 份文档，可以开始提问`}
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <AIMsgBubble key={i} msg={msg} onFeedback={(r) => msg.query_id && feedbackMut.mutate({ qid: msg.query_id, r })} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-6 pb-5 pt-3 bg-surface border-t border-border">
          {selectedDocs.size === 0 && (
            <p className="text-xs text-warning bg-amber-50 border border-amber-200 px-3 py-2 rounded-lg mb-2">
              ⚠️ 请先在左侧选择至少一份文档参与检索
            </p>
          )}
          <div className={clsx('border-2 rounded-xl overflow-hidden', isStreaming ? 'border-primary' : 'border-border focus-within:border-primary')}>
            <textarea
              value={input} onChange={e => setInput(e.target.value)} rows={2}
              onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send() } }}
              placeholder={selectedDocs.size === 0 ? '请先选择文档...' : '输入问题... (Ctrl+Enter 发送)'}
              disabled={selectedDocs.size === 0}
              className="w-full px-4 pt-3 pb-1 text-sm text-tp resize-none outline-none bg-transparent disabled:opacity-50"
            />
            <div className="flex items-center justify-end px-3 pb-2">
              {isStreaming ? (
                <button onClick={() => { stopRef.current?.(); setIsStreaming(false) }} className="flex items-center gap-1.5 h-8 px-3.5 bg-slate-900 text-white rounded-lg text-xs font-semibold">
                  <Square size={11} /> 停止
                </button>
              ) : (
                <button onClick={send} disabled={!input.trim() || selectedDocs.size === 0}
                  className="flex items-center gap-1.5 h-8 px-3.5 bg-primary text-white rounded-lg text-xs font-semibold hover:bg-primary-hover disabled:opacity-40">
                  <Send size={13} /> 发送
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right meta panel */}
      <div className="w-[260px] border-l border-border bg-surface flex-shrink-0 flex flex-col">
        <div className="px-4 py-3 border-b border-border">
          <p className="text-sm font-semibold text-tp">问答统计</p>
        </div>
        <div className="p-4 space-y-5">
          <div>
            <p className="text-[11px] font-semibold text-ts mb-2">检索模式</p>
            <span className="text-xs bg-primary/10 text-primary px-2.5 py-1 rounded-full font-semibold">
              {mode === 'kg_only' ? 'KG-Only' : '混合检索'}
            </span>
          </div>
          <div>
            <p className="text-[11px] font-semibold text-ts mb-2">参与文档</p>
            {selectedDocs.size === 0 ? (
              <p className="text-xs text-ts">尚未选择文档</p>
            ) : (
              <div className="space-y-1">
                {Array.from(selectedDocs).slice(0, 5).map(id => {
                  const d = docs.find(doc => doc.doc_id === id)
                  return d ? (
                    <div key={id} className="text-xs text-tp truncate flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" />
                      {d.original_name}
                    </div>
                  ) : null
                })}
                {selectedDocs.size > 5 && <p className="text-xs text-ts">...还有 {selectedDocs.size - 5} 份</p>}
              </div>
            )}
          </div>
          <div>
            <p className="text-[11px] font-semibold text-ts mb-2">本次对话</p>
            <div className="space-y-1.5 text-xs">
              {[
                ['问题数', messages.filter(m => m.role === 'user').length],
                ['已完成回答', messages.filter(m => m.role === 'assistant' && !m.streaming).length],
              ].map(([label, val]) => (
                <div key={String(label)} className="flex justify-between">
                  <span className="text-ts">{label}</span>
                  <span className="font-semibold text-tp">{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
