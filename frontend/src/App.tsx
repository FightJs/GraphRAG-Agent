import { Routes, Route, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import AppLayout from '@/components/layout/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import KBListPage from '@/pages/kb/KBListPage'
import DocLibPage from '@/pages/doc/DocLibPage'
import DocDetailPage from '@/pages/doc/DocDetailPage'
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
import { apiKeyApi } from '@/services/api'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireReady({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery({ queryKey: ['api-key-status'], queryFn: apiKeyApi.status })
  if (isLoading) return null
  if (!data?.ready) return <Navigate to="/settings" replace />
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
          <Route index element={<RequireReady><KBListPage /></RequireReady>} />
          <Route path="kb/:kbId" element={<RequireReady><DocLibPage /></RequireReady>} />
          <Route path="kb/:kbId/doc/:docId" element={<RequireReady><DocDetailPage /></RequireReady>} />
          <Route path="kb/:kbId/kg" element={<RequireReady><KGEntryPage /></RequireReady>} />
          <Route path="kb/:kbId/doc/:docId/index/:taskId" element={<RequireReady><IndexingPage /></RequireReady>} />
          <Route path="kb/:kbId/doc/:docId/kg" element={<RequireReady><KGPage /></RequireReady>} />
          <Route path="kb/:kbId/doc/:docId/kg/edit" element={<RequireReady><KGEditPage /></RequireReady>} />
          <Route path="kb/:kbId/doc/:docId/qa" element={<RequireReady><SingleDocQAPage /></RequireReady>} />
          <Route path="kb/:kbId/qa" element={<RequireReady><KBQAPage /></RequireReady>} />
          <Route path="history" element={<RequireReady><HistoryPage /></RequireReady>} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  )
}
