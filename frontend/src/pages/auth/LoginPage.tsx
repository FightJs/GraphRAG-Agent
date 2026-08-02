import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Zap, Search, GitBranch, Layers } from 'lucide-react'
import { authApi } from '@/services/api'
import { useAuthStore } from '@/stores/authStore'
import { useToast } from '@/hooks/useToast'

const features = [
  { icon: Layers, text: '多格式文档一键解析与索引' },
  { icon: GitBranch, text: '知识图谱可视化与人工编辑' },
  { icon: Zap, text: '流式输出，首字延迟 ≤ 2s' },
  { icon: Search, text: 'KG + 向量混合检索' },
]

export default function LoginPage() {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('')
  const [showPwd, setShowPwd] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const { setToken, setUser } = useAuthStore()
  const navigate = useNavigate()
  const toast = useToast()

  const validatePassword = (pwd: string): string => {
    if (pwd.length < 8) return '密码最少8位'
    if (!/[A-Z]/.test(pwd)) return '密码须含大写字母'
    if (!/[a-z]/.test(pwd)) return '密码须含小写字母'
    if (!/\d/.test(pwd)) return '密码须含数字'
    return ''
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (tab === 'register') {
      const pwdErr = validatePassword(password)
      if (pwdErr) { setError(pwdErr); return }
    }

    setLoading(true)
    try {
      if (tab === 'register') {
        // register returns user info only; auto-login afterwards to get access_token
        await authApi.register(email, password, username)
      }
      const data = await authApi.login(email, password)
      setToken(data.access_token)
      setUser(data.user)
      toast.success(tab === 'login' ? '登录成功' : '注册成功，欢迎加入！')
      navigate('/')
    } catch (e: unknown) {
      const resp = (e as { response?: { data?: { detail?: string | { msg?: string } } } })?.response?.data?.detail
      const msg = typeof resp === 'string' ? resp : (resp as { msg?: string })?.msg ?? '操作失败，请重试'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen">
      {/* Left brand area */}
      <div className="hidden lg:flex flex-col justify-center w-[60%] px-20 bg-gradient-to-br from-slate-900 to-blue-900 relative overflow-hidden">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiNmZmZmZmYiIGZpbGwtb3BhY2l0eT0iMC4wMyI+PHBhdGggZD0iTTM2IDM0djZoNnYtNmgtNnptNiA2djZoNnYtNmgtNnptLTYgMHY2aDZ2LTZoLTZ6Ii8+PC9nPjwvZz48L3N2Zz4=')] opacity-50" />
        <div className="relative z-10">
          {/* Logo */}
          <div className="flex items-center gap-3 mb-12">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center">
              <span className="text-white font-bold text-lg">G</span>
            </div>
            <span className="text-white font-bold text-xl">GraphRAG Agent</span>
          </div>

          <h1 className="text-5xl font-bold text-white leading-tight mb-5">
            多模态知识图谱<br />智能问答平台
          </h1>
          <p className="text-slate-300 text-lg mb-12">上传文档，自动构建知识图谱，支持混合检索与流式问答</p>

          <div className="space-y-4">
            {features.map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center flex-shrink-0">
                  <Icon size={16} className="text-blue-300" />
                </div>
                <span className="text-slate-300 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right form area */}
      <div className="flex-1 flex items-center justify-center bg-surface px-8">
        <div className="w-full max-w-[380px]">
          {/* Tab */}
          <div className="flex gap-6 mb-8 border-b border-border">
            {(['login', 'register'] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`pb-3 text-sm font-semibold transition-colors border-b-2 -mb-px ${
                  tab === t ? 'text-primary border-primary' : 'text-ts border-transparent hover:text-tp'
                }`}
              >
                {t === 'login' ? '账号登录' : '免费注册'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {tab === 'register' && (
              <div>
                <label className="block text-xs font-semibold text-tp mb-1.5">用户名</label>
                <input
                  value={username} onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  className="w-full h-11 px-3.5 border border-border rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  required
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-semibold text-tp mb-1.5">邮箱地址</label>
              <input
                type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="请输入邮箱地址"
                className="w-full h-11 px-3.5 border border-border rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                required
              />
            </div>
            <div>
              <div className="flex justify-between items-center mb-1.5">
                <label className="text-xs font-semibold text-tp">密码</label>
                {tab === 'login' && (
                  <button type="button" className="text-xs text-primary hover:underline">忘记密码？</button>
                )}
              </div>
              <div className="relative">
                <input
                  type={showPwd ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="w-full h-11 px-3.5 pr-10 border border-border rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                  required
                />
                <button
                  type="button" onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ts hover:text-tp"
                >
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {error && <p className="text-xs text-danger bg-red-50 px-3 py-2 rounded-lg">{error}</p>}

            <button
              type="submit" disabled={loading}
              className="w-full h-11 bg-primary text-white rounded-lg font-semibold text-sm hover:bg-primary-hover transition-colors disabled:opacity-60 mt-2"
            >
              {loading ? '请稍候...' : tab === 'login' ? '登录' : '创建账号'}
            </button>

            <div className="flex items-center gap-3 my-2">
              <div className="flex-1 h-px bg-border" />
              <span className="text-xs text-ts">或</span>
              <div className="flex-1 h-px bg-border" />
            </div>

            <button
              type="button"
              className="w-full h-11 border border-border rounded-lg text-sm font-medium text-tp hover:bg-bg transition-colors flex items-center justify-center gap-2"
            >
              <span className="font-bold text-[#EA4335]">G</span>
              使用 Google 账号{tab === 'login' ? '登录' : '注册'}
            </button>
          </form>

          <p className="text-center text-sm text-ts mt-6">
            {tab === 'login' ? '还没有账号？' : '已有账号？'}
            <button
              onClick={() => { setTab(tab === 'login' ? 'register' : 'login'); setError('') }}
              className="text-primary font-semibold hover:underline ml-1"
            >
              {tab === 'login' ? '立即注册' : '立即登录'}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
