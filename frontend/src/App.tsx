import { Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from '@/components/layout/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import KBListPage from '@/pages/kb/KBListPage'
import DocLibPage from '@/pages/doc/DocLibPage'
import IndexingPage from '@/pages/doc/IndexingPage'
import KGEntryPage from '@/pages/kg/KGEntryPage'
import KGPage from '@/pages/kg/KGPage'
import KGEditPage from '@/pages/kg/KGEditPage'
import SingleDocQAPage from '@/pages/qa/SingleDocQAPage'
import KBQAPage from '@/pages/qa/KBQAPage'
import HistoryPage from '@/pages/HistoryPage'
import SettingsPage from '@/pages/SettingsPage'
import { useAuthStore } from '@/stores/authStore'
import ToastContainer from '@/components/ui/ToastContainer'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <>
      <ToastContainer />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<KBListPage />} />
          <Route path="kb/:kbId" element={<DocLibPage />} />
          <Route path="kb/:kbId/kg" element={<KGEntryPage />} />
          <Route path="kb/:kbId/doc/:docId/index/:taskId" element={<IndexingPage />} />
          <Route path="kb/:kbId/doc/:docId/kg" element={<KGPage />} />
          <Route path="kb/:kbId/doc/:docId/kg/edit" element={<KGEditPage />} />
          <Route path="kb/:kbId/doc/:docId/qa" element={<SingleDocQAPage />} />
          <Route path="kb/:kbId/qa" element={<KBQAPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  )
}
