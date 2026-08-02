import { NavLink, useParams } from 'react-router-dom'
import { FileText, Share2, MessageSquare, History, Settings, Database, ChevronsUpDown } from 'lucide-react'
import { clsx } from 'clsx'

const navItems = [
  { icon: FileText, label: '文档库', to: (kbId: string) => `/kb/${kbId}` },
  { icon: Share2, label: '知识图谱', to: (kbId: string) => `/kb/${kbId}/kg` },
  { icon: MessageSquare, label: '智能问答', to: (kbId: string) => `/kb/${kbId}/qa` },
  { icon: History, label: '问答历史', to: () => '/history' },
]

export default function SideNav() {
  const { kbId } = useParams()

  return (
    <aside className="w-[240px] h-full bg-surface border-r border-border flex flex-col flex-shrink-0">
      {/* KB selector */}
      <div className="p-3">
        <button className="w-full flex items-center gap-2 bg-primary/10 rounded-lg px-3 h-11 hover:bg-primary/15 transition-colors">
          <div className="w-6 h-6 rounded-md bg-blue-500/20 flex items-center justify-center flex-shrink-0">
            <Database size={13} className="text-blue-500" />
          </div>
          <span className="flex-1 text-left text-sm font-semibold text-primary truncate">
            {kbId ? '当前知识库' : '选择知识库'}
          </span>
          <ChevronsUpDown size={13} className="text-primary flex-shrink-0" />
        </button>
      </div>

      <div className="border-t border-border mx-3" />

      {/* Nav items */}
      <nav className="flex-1 p-3 space-y-0.5">
        {navItems.map(({ icon: Icon, label, to }) => {
          const href = kbId ? to(kbId) : to('')
          return (
            <NavLink
              key={label}
              to={href}
              end={label === '文档库'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2.5 px-3 h-10 rounded-lg text-sm transition-colors',
                  isActive
                    ? 'bg-primary/10 text-primary font-semibold'
                    : 'text-ts hover:bg-bg hover:text-tp'
                )
              }
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
