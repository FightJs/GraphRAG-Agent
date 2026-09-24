import {
  Database, Book, Briefcase, GraduationCap, FlaskConical, Code2,
  Heart, Lightbulb, Rocket, Star, Folder, Globe, Scale, Landmark,
} from 'lucide-react'

export const KB_ICONS = [
  { id: 'database', label: '数据' },
  { id: 'book', label: '书本' },
  { id: 'briefcase', label: '公文包' },
  { id: 'graduation-cap', label: '学术' },
  { id: 'flask', label: '实验' },
  { id: 'code', label: '代码' },
  { id: 'heart', label: '健康' },
  { id: 'lightbulb', label: '灵感' },
  { id: 'rocket', label: '创业' },
  { id: 'star', label: '精选' },
  { id: 'folder', label: '文件' },
  { id: 'globe', label: '全球' },
  { id: 'scale', label: '法律' },
  { id: 'landmark', label: '机构' },
] as const

export type KbIconId = (typeof KB_ICONS)[number]['id'] | string

const ICON_MAP: Record<string, typeof Database> = {
  database: Database,
  book: Book,
  briefcase: Briefcase,
  'graduation-cap': GraduationCap,
  flask: FlaskConical,
  code: Code2,
  heart: Heart,
  lightbulb: Lightbulb,
  rocket: Rocket,
  star: Star,
  folder: Folder,
  globe: Globe,
  scale: Scale,
  landmark: Landmark,
}

export default function KbIcon({
  icon,
  color,
  size = 22,
  box = 44,
  radius = 12,
}: {
  icon?: string
  color?: string
  size?: number
  box?: number
  radius?: number
}) {
  const Icon = ICON_MAP[icon || 'database'] ?? Database
  const c = color || '#3B82F6'
  return (
    <div
      className="flex items-center justify-center flex-shrink-0"
      style={{ width: box, height: box, borderRadius: radius, background: c + '20' }}
    >
      <Icon size={size} style={{ color: c }} />
    </div>
  )
}
