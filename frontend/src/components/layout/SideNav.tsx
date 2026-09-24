import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FileText, Share2, MessageSquare, History, Settings, ChevronsUpDown } from 'lucide-react'
import KbIcon from '@/components/ui/KbIcon'
import { clsx } from 'clsx'
import { kbApi } from '@/services/api'

const navItems = [
  { icon: FileText, label: '文档库', to: (kbId: string) => `/kb/${kbId}`, end: true, needsKb: true },
  { icon: Share2, label: '知识图谱', to: (kbId: string) => `/kb/${kbId}/kg`, end: false, needsKb: true },
  { icon: MessageSquare, label: '智能问答', to: (kbId: string) => `/kb/${kbId}/qa`, end: false, needsKb: true },
  { icon: History, label: '问答历史', to: () => '/history', end: false, needsKb: false },
]

const LAST_KB_KEY = 'graphrag-last-kb'

function resolveKbId(pathname: string): string | null {
  const m = pathname.match(/^\/kb\/([^/]+)/)
  return m?.[1] ?? null
}

export default function SideNav() {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  // 布局层 useParams 拿不到子路由的 kbId，从路径解析并记忆最近一次
  const pathKbId = resolveKbId(pathname)
  const storedKbId = typeof window !== 'undefined' ? sessionStorage.getItem(LAST_KB_KEY) : null
  const kbId = pathKbId ?? (pathname === '/' || pathname.startsWith('/kb/') ? null : storedKbId)

  if (pathKbId) {
    sessionStorage.setItem(LAST_KB_KEY, pathKbId)
  }

  const { data: kbs = [] } = useQuery({ queryKey: ['kbs'], queryFn: kbApi.list, staleTime: 30_000 })
  const currentKb = kbs.find(k => k.kb_id === kbId)

  return (
    <aside className="w-[240px] h-full bg-surface border-r border-border flex flex-col flex-shrink-0">
      {/* KB selector → 回到知识库列表 */}
      <div className="p-3">
        <button
          onClick={() => navigate('/')}
          title="切换知识库"
          className="w-full flex items-center gap-2 bg-primary/10 rounded-lg px-3 h-11 hover:bg-primary/15 transition-colors"
        >
          <KbIcon icon={currentKb?.icon} color={currentKb?.color || '#3B82F6'} size={13} box={24} radius={6} />
          <span className="flex-1 text-left text-sm font-semibold text-primary truncate">
            {currentKb?.name || (kbId ? '当前知识库' : '选择知识库')}
          </span>
          <ChevronsUpDown size={13} className="text-primary flex-shrink-0" />
        </button>
        <p className="text-[10px] text-ts px-3 mt-1.5">
          {kbId ? '点击可切换 / 返回列表' : '先在首页进入一个知识库'}
        </p>
      </div>

      <div className="border-t border-border mx-3" />

      {/* Nav items */}
      <nav className="flex-1 p-3 space-y-0.5">
        {navItems.map(({ icon: Icon, label, to, end, needsKb }) => {
          const disabled = needsKb && !kbId
          const href = !needsKb ? to('') : kbId ? to(kbId) : '/'

          return (
            <NavLink
              key={label}
              to={href}
              end={end}
              title={disabled ? '请先选择知识库' : undefined}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2.5 px-3 h-10 rounded-lg text-sm transition-colors',
                  disabled
                    ? 'text-ts/50 cursor-not-allowed opacity-60'
                    : isActive
                      ? 'bg-primary/10 text-primary font-semibold'
                      : 'text-ts hover:bg-bg hover:text-tp'
                )
              }
              onClick={(e) => {
                if (disabled) {
                  e.preventDefault()
                  navigate('/')
                }
              }}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          )
        })}
      </nav>

      {/* Settings */}
      <div className="p-3 border-t border-border">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-2.5 px-3 h-10 rounded-lg text-sm transition-colors',
              isActive ? 'bg-primary/10 text-primary font-semibold' : 'text-ts hover:bg-bg hover:text-tp'
            )
          }
        >
          <Settings size={16} />
          设置
        </NavLink>
      </div>
    </aside>
  )
}
