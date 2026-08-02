import { Bell, ChevronDown, LogOut, Settings } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { authApi } from '@/services/api'

export default function TopNav() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const handleLogout = async () => {
    await authApi.logout()
    logout()
    navigate('/login')
  }

  return (
    <header className="h-[60px] bg-surface border-b border-border flex items-center justify-between px-6 flex-shrink-0 z-10">
      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center">
          <span className="text-white text-xs font-bold">G</span>
        </div>
        <span className="font-bold text-[15px] text-tp">GraphRAG Agent</span>
      </div>

      {/* Right */}
      <div className="flex items-center gap-4">
        <button className="text-ts hover:text-tp transition-colors relative">
          <Bell size={18} />
        </button>
        <div className="relative">
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 hover:bg-bg rounded-lg px-2 py-1 transition-colors"
          >
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-white text-sm font-semibold">
              {user?.username?.charAt(0) ?? 'U'}
            </div>
            <span className="text-sm font-medium text-tp">{user?.username ?? '用户'}</span>
            <ChevronDown size={14} className="text-ts" />
          </button>
          {open && (
            <div className="absolute right-0 top-full mt-1 w-44 bg-surface border border-border rounded-xl shadow-lg py-1 z-50">
              <button
                onClick={() => { navigate('/settings'); setOpen(false) }}
                className="w-full flex items-center gap-2 px-4 py-2 text-sm text-tp hover:bg-bg"
              >
                <Settings size={14} className="text-ts" /> 个人设置
              </button>
              <div className="border-t border-border my-1" />
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-4 py-2 text-sm text-danger hover:bg-red-50"
              >
                <LogOut size={14} /> 退出登录
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
