import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { useToast } from '@/hooks/useToast'
import { webhookApi } from '@/services/api'
import type { WebhookCreatePayload } from '@/types'
import { User, Lock, Key, Bell, Webhook, Plus, Trash2, Construction, ExternalLink } from 'lucide-react'

function UndevelopedBadge({ text = '后端接口未实现' }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl mb-6">
      <Construction size={15} className="text-amber-600 flex-shrink-0" />
      <p className="text-xs text-amber-700">{text}，此功能暂不可用</p>
    </div>
  )
}

export default function SettingsPage() {
  const user = useAuthStore(s => s.user)
  const toast = useToast()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState('profile')

  // Webhook form state
  const [whUrl, setWhUrl] = useState('')
  const [whSecret, setWhSecret] = useState('')
  const [whEvents, setWhEvents] = useState<string[]>(['index.completed', 'index.failed'])

  const tabs = [
    { id: 'profile', icon: User, label: '个人信息' },
    { id: 'security', icon: Lock, label: '账号安全' },
    { id: 'apikey', icon: Key, label: 'API Key' },
    { id: 'webhook', icon: Webhook, label: 'Webhook' },
    { id: 'notify', icon: Bell, label: '通知设置' },
  ]

  // Webhooks
  const { data: webhooks = [], isLoading: whLoading } = useQuery({
    queryKey: ['webhooks'],
    queryFn: webhookApi.list,
    enabled: activeTab === 'webhook',
  })

  const createWhMut = useMutation({
    mutationFn: (p: WebhookCreatePayload) => webhookApi.create(p),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['webhooks'] })
      setWhUrl(''); setWhSecret('')
      toast.success('Webhook 已创建')
    },
    onError: () => toast.error('Webhook 创建失败'),
  })

  const deleteWhMut = useMutation({
    mutationFn: webhookApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['webhooks'] }); toast.success('Webhook 已删除') },
  })

  const handleCreateWebhook = () => {
    if (!whUrl.startsWith('https://')) { toast.error('URL 必须以 https:// 开头'); return }
    if (whEvents.length === 0) { toast.error('请至少选择一个触发事件'); return }
    createWhMut.mutate({ url: whUrl, events: whEvents, secret: whSecret || undefined })
  }

  const toggleEvent = (ev: string) => {
    setWhEvents(prev => prev.includes(ev) ? prev.filter(e => e !== ev) : [...prev, ev])
  }

  return (
    <div className="h-full flex">
      {/* Side tabs */}
      <div className="w-52 border-r border-border bg-surface flex-shrink-0 p-3 space-y-0.5">
        <p className="text-[11px] font-semibold text-ts px-3 mb-2 mt-1">设置</p>
        {tabs.map(({ id, icon: Icon, label }) => (
          <button key={id} onClick={() => setActiveTab(id)}
            className={`w-full flex items-center gap-2.5 px-3 h-10 rounded-lg text-sm transition-colors ${
              activeTab === id ? 'bg-primary/10 text-primary font-semibold' : 'text-ts hover:bg-bg hover:text-tp'
            }`}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-8">

        {/* Profile — 后端无接口 */}
        {activeTab === 'profile' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-6">个人信息</h2>
            <UndevelopedBadge text="个人信息修改接口（v2.0 规范未定义）" />
            <div className="space-y-5 opacity-60 pointer-events-none">
              <div className="flex items-center gap-5 mb-8">
                <div className="w-20 h-20 rounded-full bg-primary flex items-center justify-center text-white text-3xl font-bold">
                  {user?.username?.charAt(0) ?? 'U'}
                </div>
                <div>
                  <p className="text-sm font-semibold text-tp">{user?.username}</p>
                  <p className="text-xs text-ts">{user?.email}</p>
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">用户名</label>
                <input value={user?.username ?? ''} disabled
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm bg-bg text-ts cursor-not-allowed" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">邮箱地址</label>
                <input value={user?.email ?? ''} disabled
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm bg-bg text-ts cursor-not-allowed" />
              </div>
              <button disabled className="h-10 px-6 bg-primary text-white rounded-lg text-sm font-semibold opacity-50 cursor-not-allowed">
                保存修改
              </button>
            </div>
          </div>
        )}

        {/* Security — 后端无接口 */}
        {activeTab === 'security' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-6">账号安全</h2>
            <UndevelopedBadge text="密码修改接口（v2.0 规范未定义）" />
            <div className="space-y-4 opacity-60 pointer-events-none">
              {['当前密码', '新密码', '确认新密码'].map(label => (
                <div key={label}>
                  <label className="block text-xs font-semibold text-tp mb-1.5">{label}</label>
                  <input type="password" disabled className="w-full h-10 px-3 border border-border rounded-lg text-sm bg-bg cursor-not-allowed" />
                </div>
              ))}
              <button disabled className="h-10 px-6 bg-primary text-white rounded-lg text-sm font-semibold opacity-50 cursor-not-allowed">
                修改密码
              </button>
            </div>
          </div>
        )}

        {/* API Key — 仅展示，无需后端接口 */}
        {activeTab === 'apikey' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-2">API Key</h2>
            <p className="text-sm text-ts mb-6">API Key 由系统管理员通过 <code className="bg-bg px-1 rounded text-xs">backend/.env</code> 配置，前端无法直接查看或修改。</p>
            <div className="bg-bg border border-border rounded-xl p-5 space-y-3">
              {['DeepSeek API', 'MinerU API', 'Embedding API'].map(name => (
                <div key={name} className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-tp">{name}</p>
                    <p className="text-xs text-ts font-mono">sk-**********************</p>
                  </div>
                  <span className="text-xs bg-green-100 text-success px-2 py-0.5 rounded-full font-semibold">已配置</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Webhook — 已接入 /api/v2/webhooks */}
        {activeTab === 'webhook' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-2">Webhook 管理</h2>
            <p className="text-sm text-ts mb-6">索引完成后，系统将向配置的 URL 发送 POST 回调。</p>

            {/* 已有 Webhook 列表 */}
            {whLoading ? (
              <div className="space-y-2 mb-6">{[...Array(2)].map((_, i) => <div key={i} className="h-14 rounded-xl skeleton" />)}</div>
            ) : webhooks.length > 0 && (
              <div className="mb-6 space-y-2">
                <p className="text-xs font-semibold text-ts mb-2">已配置 ({webhooks.length})</p>
                {webhooks.map(wh => (
                  <div key={wh.webhook_id} className="flex items-center justify-between bg-bg border border-border rounded-xl px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${wh.is_active ? 'bg-success' : 'bg-ts'}`} />
                        <a href={wh.url} target="_blank" rel="noopener noreferrer"
                          className="text-xs font-medium text-tp truncate hover:text-primary flex items-center gap-0.5">
                          {wh.url} <ExternalLink size={10} />
                        </a>
                      </div>
                      <p className="text-[10px] text-ts pl-4">{wh.events.join(', ')}</p>
                    </div>
                    <button onClick={() => deleteWhMut.mutate(wh.webhook_id)}
                      className="ml-3 text-ts hover:text-danger flex-shrink-0">
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* 新增表单 */}
            <div className="border border-border rounded-xl p-5 space-y-4">
              <p className="text-xs font-semibold text-ts">新增 Webhook</p>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">回调 URL (必须 https://)</label>
                <input value={whUrl} onChange={e => setWhUrl(e.target.value)}
                  placeholder="https://your-server.com/webhook"
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">签名密钥（可选）</label>
                <input value={whSecret} onChange={e => setWhSecret(e.target.value)}
                  placeholder="用于 HMAC-SHA256 签名验证"
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">触发事件</label>
                <div className="space-y-2">
                  {[
                    { val: 'index.completed', label: 'index.completed（索引完成）' },
                    { val: 'index.failed', label: 'index.failed（索引失败）' },
                  ].map(({ val, label }) => (
                    <label key={val} className="flex items-center gap-2 text-sm text-tp cursor-pointer">
                      <input type="checkbox" checked={whEvents.includes(val)} onChange={() => toggleEvent(val)}
                        className="w-4 h-4 accent-primary" /> {label}
                    </label>
                  ))}
                </div>
              </div>
              <button onClick={handleCreateWebhook} disabled={createWhMut.isPending || !whUrl}
                className="flex items-center gap-1.5 h-10 px-5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover disabled:opacity-50">
                <Plus size={14} />{createWhMut.isPending ? '创建中...' : '添加 Webhook'}
              </button>
            </div>
          </div>
        )}

        {/* Notify — 后端无接口 */}
        {activeTab === 'notify' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-6">通知设置</h2>
            <UndevelopedBadge text="通知偏好设置接口（v2.0 规范未定义）" />
            <div className="space-y-4 opacity-60 pointer-events-none">
              {[
                { label: '索引完成通知', desc: '文档索引完成时发送站内通知' },
                { label: '索引失败通知', desc: '索引过程发生错误时提醒' },
                { label: '问答历史统计', desc: '每周发送问答统计摘要' },
              ].map(({ label, desc }) => (
                <div key={label} className="flex items-center justify-between py-3 border-b border-border">
                  <div>
                    <p className="text-sm font-semibold text-tp">{label}</p>
                    <p className="text-xs text-ts">{desc}</p>
                  </div>
                  <input type="checkbox" defaultChecked className="w-4 h-4 accent-primary" />
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
