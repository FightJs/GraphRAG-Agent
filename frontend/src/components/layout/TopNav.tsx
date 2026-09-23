import { Bell, Check, ChevronDown, LogOut, Settings, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { authApi, notifyApi } from '@/services/api'

function formatTime(iso: string) {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ''
  const diff = Date.now() - t.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return t.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function TopNav() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)

  const { data: notifData, refetch: refetchNotifs } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => notifyApi.list(20),
    enabled: true,
    refetchInterval: 30_000,
  })
  const unread = notifData?.unread ?? 0

  const markReadMut = useMutation({
    mutationFn: notifyApi.markRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
      qc.invalidateQueries({ queryKey: ['notify-unread'] })
    },
  })
  const markAllMut = useMutation({
    mutationFn: notifyApi.markAllRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
  const removeMut = useMutation({
    mutationFn: notifyApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

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
        <div className="relative" ref={notifRef}>
          <button
            className="text-ts hover:text-tp transition-colors relative"
            aria-label="通知"
            onClick={() => {
              setNotifOpen((v) => !v)
              setOpen(false)
              if (!notifOpen) refetchNotifs()
            }}
          >
            <Bell size={18} />
            {unread > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-danger text-white text-[10px] font-semibold flex items-center justify-center">
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </button>
          {notifOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 bg-surface border border-border rounded-xl shadow-lg z-50 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <p className="text-sm font-semibold text-tp">通知</p>
                <div className="flex items-center gap-2">
                  {unread > 0 && (
                    <button
                      onClick={() => markAllMut.mutate()}
                      className="text-xs text-primary hover:underline flex items-center gap-0.5"
                    >
                      <Check size={12} /> 全部已读
                    </button>
                  )}
                  <button
                    onClick={() => { navigate('/settings'); setNotifOpen(false) }}
                    className="text-xs text-ts hover:text-tp"
                  >
                    设置
                  </button>
                </div>
              </div>
              <div className="max-h-80 overflow-auto">
                {!notifData || notifData.items.length === 0 ? (
                  <div className="px-4 py-8 text-center text-xs text-ts">暂无通知</div>
                ) : (
                  notifData.items.map((n) => (
                    <div
                      key={n.notification_id}
                      className={`group flex items-start gap-2 px-4 py-3 border-b border-border last:border-b-0 hover:bg-bg ${
                        n.is_read ? 'opacity-60' : ''
                      }`}
                    >
                      <button
                        className="flex-1 min-w-0 text-left"
                        onClick={() => {
                          if (!n.is_read) markReadMut.mutate(n.notification_id)
                        }}
                      >
                        <div className="flex items-center gap-2">
                          {!n.is_read && <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" />}
                          <p className="text-xs font-semibold text-tp truncate">{n.title}</p>
                        </div>
                        <p className="text-xs text-ts mt-0.5 line-clamp-2">{n.body}</p>
                        <p className="text-[10px] text-ts mt-1">{formatTime(n.created_at)}</p>
                      </button>
                      <button
                        onClick={() => removeMut.mutate(n.notification_id)}
                        className="text-ts hover:text-danger opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 mt-0.5"
                        aria-label="删除通知"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
        <div className="relative">
          <button
            onClick={() => { setOpen(!open); setNotifOpen(false) }}
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
