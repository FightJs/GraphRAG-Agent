import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle, XCircle, Loader, ArrowLeft, Share2, MessageSquare } from 'lucide-react'
import { docApi } from '@/services/api'
import { clsx } from 'clsx'

const STAGE_LABELS = ['文档解析', 'Markdown 转换', '文本分块', 'KG 实体抽取', '向量化索引']

export default function IndexingPage() {
  const { kbId, docId, taskId } = useParams<{ kbId: string; docId: string; taskId: string }>()
  const navigate = useNavigate()

  const { data: task } = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => docApi.getTask(taskId!),
    enabled: !!taskId,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'indexing' ? 1500 : false
    },
  })

  const isDone = task?.status === 'indexed'
  const isFailed = task?.status === 'failed'
  const progress = task?.progress ?? 0

  return (
    <div className="h-full flex flex-col items-center justify-center gap-8 p-8">
      {/* Back */}
      <button onClick={() => navigate(`/kb/${kbId}`)} className="absolute top-6 left-72 flex items-center gap-1.5 text-sm text-ts hover:text-tp">
        <ArrowLeft size={15} /> 返回文档库
      </button>

      <div className="w-full max-w-xl bg-surface rounded-2xl border border-border p-8">
        {/* Progress number */}
        <div className="text-center mb-8">
          <div className={clsx('text-7xl font-bold tabular-nums mb-2', isDone ? 'text-success' : isFailed ? 'text-danger' : 'text-primary')}>
            {isDone ? '100' : isFailed ? '!' : progress}
            {!isDone && !isFailed && <span className="text-2xl">%</span>}
          </div>
          <p className="text-ts text-sm">
            {isDone ? '索引完成 🎉' : isFailed ? '索引失败' : '正在构建知识图谱...'}
          </p>
        </div>

        {/* Progress bar */}
        <div className="w-full h-2 bg-bg rounded-full mb-8">
          <div
            className={clsx('h-2 rounded-full transition-all duration-500', isDone ? 'bg-success' : isFailed ? 'bg-danger' : 'bg-primary')}
            style={{ width: `${isDone ? 100 : progress}%` }}
          />
        </div>

        {/* Stages */}
        <div className="flex items-center justify-between">
          {STAGE_LABELS.map((label, i) => {
            const stageData = task?.stages?.[i]
            const done = stageData?.status === 'done'
            const running = stageData?.status === 'running'
            const failed = stageData?.status === 'failed'
            return (
              <div key={label} className="flex flex-col items-center gap-2 flex-1">
                {i > 0 && <div className={clsx('absolute')} />}
                <div className={clsx(
                  'w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold transition-all',
                  done ? 'bg-success text-white' : running ? 'bg-primary text-white animate-pulse' : failed ? 'bg-danger text-white' : 'bg-bg text-ts border border-border'
                )}>
                  {done ? <CheckCircle size={18} /> : failed ? <XCircle size={18} /> : running ? <Loader size={16} className="animate-spin" /> : <span className="text-xs">{i + 1}</span>}
                </div>
                <span className="text-[10px] text-ts text-center leading-tight w-14">{label}</span>
              </div>
            )
          })}
        </div>

        {/* Actions */}
        {isDone && (
          <div className="flex gap-3 mt-8">
            <button
              onClick={() => navigate(`/kb/${kbId}/doc/${docId}/kg`)}
              className="flex-1 flex items-center justify-center gap-2 h-10 border border-border rounded-lg text-sm text-tp hover:bg-bg"
            >
              <Share2 size={15} /> 查看知识图谱
            </button>
            <button
              onClick={() => navigate(`/kb/${kbId}/doc/${docId}/qa`)}
              className="flex-1 flex items-center justify-center gap-2 h-10 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover"
            >
              <MessageSquare size={15} /> 开始问答
            </button>
          </div>
        )}

        {isFailed && task && (
          <div className="mt-6 p-4 bg-red-50 rounded-lg">
            <p className="text-xs text-danger">{(task as { error_message?: string }).error_message ?? '索引过程中发生错误，请重试'}</p>
          </div>
        )}
      </div>
    </div>
  )
}
