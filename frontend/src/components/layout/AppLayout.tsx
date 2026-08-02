import { Outlet } from 'react-router-dom'
import TopNav from './TopNav'
import SideNav from './SideNav'

export default function AppLayout() {
  return (
    <div className="flex flex-col h-screen bg-bg overflow-hidden">
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <SideNav />
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
