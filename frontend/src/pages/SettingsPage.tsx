import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { useToast } from '@/hooks/useToast'
import { authApi, apiKeyApi, webhookApi, notifyApi, systemApi } from '@/services/api'
import type { ApiKeyProvider, WebhookCreatePayload, NotificationPreferences, NotificationPreferencesPatch } from '@/types'
import { User, Lock, Key, Bell, Webhook, Plus, Trash2, ExternalLink, Activity } from 'lucide-react'

export default function SettingsPage() {
  const user = useAuthStore(s => s.user)
  const setUser = useAuthStore(s => s.setUser)
  const toast = useToast()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState('profile')
  const [selectedProvider, setSelectedProvider] = useState<ApiKeyProvider>('deepseek')
  const [apiKey, setApiKey] = useState('')

  // Profile form
  const [username, setUsername] = useState(user?.username ?? '')
  const [email, setEmail] = useState(user?.email ?? '')

  // Password form
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

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
    { id: 'system', icon: Activity, label: '系统状态' },
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

  // Profile
  const updateMeMut = useMutation({
    mutationFn: () => authApi.updateMe({ username, email }),
    onSuccess: (updated) => {
      if (user) setUser({ ...user, username: updated.username, email: updated.email })
      toast.success('个人信息已保存')
    },
    onError: (error: any) => toast.error(error?.response?.data?.detail?.msg ?? '保存失败'),
  })

  // Change password
  const changePwdMut = useMutation({
    mutationFn: () => authApi.changePassword(currentPassword, newPassword),
    onSuccess: () => {
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
      toast.success('密码已修改')
    },
    onError: (error: any) => toast.error(error?.response?.data?.detail?.msg ?? '密码修改失败'),
  })

  const handleChangePassword = () => {
    if (newPassword.length < 8) { toast.error('新密码至少 8 位'); return }
    if (newPassword !== confirmPassword) { toast.error('两次输入的新密码不一致'); return }
    changePwdMut.mutate()
  }

  // System status
  const { data: sysStatus, isLoading: sysLoading } = useQuery({
    queryKey: ['system-status'],
    queryFn: systemApi.status,
    enabled: activeTab === 'system',
    refetchInterval: 15000,
  })

  const { data: keyStatus, isLoading: keyLoading } = useQuery({
    queryKey: ['api-key-status'], queryFn: apiKeyApi.status, enabled: activeTab === 'apikey',
  })
  const saveKeyMut = useMutation({
    mutationFn: () => apiKeyApi.save(selectedProvider, apiKey),
    onSuccess: () => {
      setApiKey('')
      qc.invalidateQueries({ queryKey: ['api-key-status'] })
      toast.success('密钥验证并保存成功')
    },
    onError: (error: any) => toast.error(error?.response?.data?.detail?.msg ?? '密钥验证失败，请检查后重试'),
  })
  const deleteKeyMut = useMutation({
    mutationFn: apiKeyApi.remove,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['api-key-status'] }); toast.success('密钥已删除') },
    onError: () => toast.error('删除密钥失败'),
  })

  // Notification preferences
  const { data: notifyPrefs, isLoading: notifyLoading } = useQuery({
    queryKey: ['notify-preferences'],
    queryFn: notifyApi.getPreferences,
    enabled: activeTab === 'notify',
  })

  const updateNotifyMut = useMutation({
    mutationFn: (patch: NotificationPreferencesPatch) => notifyApi.updatePreferences(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notify-preferences'] })
      toast.success('通知偏好已保存')
    },
    onError: () => toast.error('通知偏好保存失败'),
  })

  const notifyItems: { key: keyof NotificationPreferences; label: string; desc: string }[] = [
    { key: 'index_completed', label: '索引完成通知', desc: '文档索引完成时发送站内通知' },
    { key: 'index_failed', label: '索引失败通知', desc: '索引过程发生错误时提醒' },
    { key: 'qa_weekly_digest', label: '问答历史统计', desc: '每周发送问答统计摘要' },
  ]

  const toggleNotify = (key: keyof NotificationPreferences) => {
    if (!notifyPrefs) return
    updateNotifyMut.mutate({ [key]: !notifyPrefs[key] })
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

        {/* Profile — 已接入 PATCH /api/v2/auth/me */}
        {activeTab === 'profile' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-6">个人信息</h2>
            <div className="space-y-5">
              <div className="flex items-center gap-5 mb-8">
                <div className="w-20 h-20 rounded-full bg-primary flex items-center justify-center text-white text-3xl font-bold">
                  {(username || user?.username || 'U').charAt(0)}
                </div>
                <div>
                  <p className="text-sm font-semibold text-tp">{username || user?.username}</p>
                  <p className="text-xs text-ts">{email || user?.email}</p>
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">用户名</label>
                <input value={username} onChange={e => setUsername(e.target.value)}
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">邮箱地址</label>
                <input value={email} onChange={e => setEmail(e.target.value)} type="email"
                  className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
              </div>
              <button
                onClick={() => updateMeMut.mutate()}
                disabled={updateMeMut.isPending || (!username.trim() || !email.trim())}
                className="h-10 px-6 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover disabled:opacity-50">
                {updateMeMut.isPending ? '保存中...' : '保存修改'}
              </button>
            </div>
          </div>
        )}

        {/* Security — 已接入 POST /api/v2/auth/change-password */}
        {activeTab === 'security' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-6">账号安全</h2>
            <div className="space-y-4">
              {[
                { label: '当前密码', value: currentPassword, set: setCurrentPassword },
                { label: '新密码', value: newPassword, set: setNewPassword },
                { label: '确认新密码', value: confirmPassword, set: setConfirmPassword },
              ].map(({ label, value, set }) => (
                <div key={label}>
                  <label className="block text-xs font-semibold text-tp mb-1.5">{label}</label>
                  <input type="password" value={value} onChange={e => set(e.target.value)} autoComplete="new-password"
                    className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
                </div>
              ))}
              <button
                onClick={handleChangePassword}
                disabled={changePwdMut.isPending || !currentPassword || !newPassword || !confirmPassword}
                className="h-10 px-6 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover disabled:opacity-50">
                {changePwdMut.isPending ? '修改中...' : '修改密码'}
              </button>
            </div>
          </div>
        )}

        {/* API Key */}
        {activeTab === 'apikey' && (
          <div className="max-w-xl">
            <h2 className="text-xl font-bold text-tp mb-2">连接服务</h2>
            <p className="text-sm text-ts mb-6">完成三项凭据验证后，知识库、索引和问答功能才会开放。保存后仅显示末四位提示。</p>
            <div className="space-y-2 mb-6">
              {[
                ['deepseek', 'DeepSeek', '用于知识图谱抽取与问答'],
                ['mineru', 'MinerU', '用于云端文档解析验证'],
                ['embedding', 'OpenRouter Embedding', 'qwen/qwen3-embedding-8b'],
              ].map(([provider, label, description]) => {
                const status = keyStatus?.providers.find(item => item.provider === provider)
                return <button key={provider} onClick={() => setSelectedProvider(provider as ApiKeyProvider)}
                  className={`w-full text-left border px-4 py-3 rounded-lg transition-colors ${selectedProvider === provider ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div><p className="text-sm font-semibold text-tp">{label}</p><p className="text-xs text-ts mt-1">{description}</p></div>
                    <div className="flex items-center gap-2">
                      {status?.configured && <span className="text-xs font-mono text-ts">••••{status.key_hint}</span>}
                      <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${status?.is_verified ? 'bg-green-100 text-success' : 'bg-bg text-ts'}`}>{status?.is_verified ? '已验证' : '未配置'}</span>
                      {status?.configured && <span onClick={(event) => { event.stopPropagation(); deleteKeyMut.mutate(provider as ApiKeyProvider) }} className="text-danger hover:underline text-xs">删除</span>}
                    </div>
                  </div>
                </button>
              })}
            </div>
            <div className="border border-border rounded-lg p-5 space-y-3">
              <div><p className="text-sm font-semibold text-tp">添加 {selectedProvider === 'deepseek' ? 'DeepSeek' : selectedProvider === 'mineru' ? 'MinerU' : 'OpenRouter Embedding'} 密钥</p><p className="text-xs text-ts mt-1">将先进行服务端验证，验证成功后才会加密保存。</p></div>
              <input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} autoComplete="off" placeholder="粘贴 API Key"
                className="w-full h-10 px-3 border border-border rounded-lg text-sm focus:outline-none focus:border-primary" />
              <button onClick={() => saveKeyMut.mutate()} disabled={apiKey.length < 8 || saveKeyMut.isPending || keyLoading}
                className="h-10 px-5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-hover disabled:opacity-50">
                {saveKeyMut.isPending ? '验证中...' : '验证并保存'}
              </button>
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

        {/* Notify — 已接入 /api/v2/settings/notifications/preferences */}
        {activeTab === 'notify' && (
          <div className="max-w-lg">
            <h2 className="text-xl font-bold text-tp mb-2">通知设置</h2>
            <p className="text-sm text-ts mb-6">管理站内通知偏好。开启后，对应事件会在顶栏通知铃铛中提醒。</p>
            {notifyLoading ? (
              <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-16 rounded-xl skeleton" />)}</div>
            ) : (
              <div className="space-y-0">
                {notifyItems.map(({ key, label, desc }) => {
                  const checked = notifyPrefs?.[key] ?? false
                  return (
                    <div key={key} className="flex items-center justify-between py-4 border-b border-border">
                      <div>
                        <p className="text-sm font-semibold text-tp">{label}</p>
                        <p className="text-xs text-ts mt-0.5">{desc}</p>
                      </div>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={checked}
                        aria-label={label}
                        disabled={updateNotifyMut.isPending}
                        onClick={() => toggleNotify(key)}
                        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 disabled:opacity-50 ${
                          checked ? 'bg-primary' : 'bg-border'
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                            checked ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* System status */}
        {activeTab === 'system' && (
          <div className="max-w-2xl">
            <h2 className="text-xl font-bold text-tp mb-2">系统状态</h2>
            <p className="text-sm text-ts mb-6">运行健康、存储与数据概况（每 15 秒自动刷新）。</p>
            {sysLoading || !sysStatus ? (
              <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-20 rounded-xl skeleton" />)}</div>
            ) : (
              <div className="space-y-6">
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: '数据库', ok: sysStatus.database.ok },
                    { label: '向量库', ok: sysStatus.vector_store.ok },
                    { label: 'API 服务', ok: sysStatus.status === 'ok' },
                  ].map(({ label, ok }) => (
                    <div key={label} className="border border-border rounded-xl p-4 text-center">
                      <div className={`w-2.5 h-2.5 rounded-full mx-auto mb-2 ${ok ? 'bg-success' : 'bg-danger'}`} />
                      <p className="text-sm font-semibold text-tp">{label}</p>
                      <p className="text-xs text-ts mt-1">{ok ? '正常' : '异常'}</p>
                    </div>
                  ))}
                </div>

                <div className="border border-border rounded-xl p-5">
                  <p className="text-xs font-semibold text-ts mb-3">数据概况</p>
                  <div className="grid grid-cols-3 gap-4">
                    {[
                      { label: '文档总数', value: sysStatus.stats.docs_total },
                      { label: '已索引', value: sysStatus.stats.docs_indexed },
                      { label: '索引中', value: sysStatus.stats.docs_indexing },
                      { label: '失败', value: sysStatus.stats.docs_failed },
                      { label: '用户', value: sysStatus.stats.users },
                      { label: '问答记录', value: sysStatus.stats.qa_records },
                    ].map(({ label, value }) => (
                      <div key={label}>
                        <p className="text-2xl font-bold text-tp tabular-nums">{value}</p>
                        <p className="text-xs text-ts mt-0.5">{label}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="border border-border rounded-xl p-5">
                  <p className="text-xs font-semibold text-ts mb-3">外部服务凭据</p>
                  <div className="space-y-2">
                    {Object.entries(sysStatus.providers).map(([name, state]) => (
                      <div key={name} className="flex items-center justify-between text-sm">
                        <span className="text-tp">{name}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${state === 'verified' ? 'bg-green-100 text-success' : 'bg-bg text-ts'}`}>
                          {state === 'verified' ? '已验证' : '未配置'}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-ts mt-3">
                    MOCK 模式：{sysStatus.mock_external_services ? '开启（不调用真实外部 API）' : '关闭'}
                  </p>
                </div>

                <div className="border border-border rounded-xl p-5 text-xs text-ts space-y-1 font-mono">
                  <p>version: {sysStatus.version}</p>
                  <p>milvus: {sysStatus.vector_store.uri}</p>
                  <p>upload_dir: {sysStatus.storage.upload_dir}</p>
                  <p>kg_dir: {sysStatus.storage.kg_dir}</p>
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}
