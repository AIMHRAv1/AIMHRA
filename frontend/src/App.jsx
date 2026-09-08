import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/auth/Login'
import HcwDashboard from './pages/hcw/Dashboard'
import PatientList from './pages/hcw/Patients'
import PatientNew from './pages/hcw/PatientNew'
import PatientDetail from './pages/hcw/PatientDetail'
import Alerts from './pages/hcw/Alerts'
import HcwReports from './pages/hcw/Reports'
import AdminDashboard from './pages/admin/Dashboard'
import AdminUsers from './pages/admin/Users'
import AdminModels from './pages/admin/Models'
import AdminKnowledge from './pages/admin/Knowledge'
import AdminAudit from './pages/admin/Audit'

function RoleDashboard() {
  const { user } = useAuth()
  if (user?.role === 'ADMIN') return <AdminDashboard />
  if (user?.role === 'HEALTHCARE_WORKER') return <HcwDashboard />
  return <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Navigate to="/app/dashboard" replace />} />

      <Route path="/app" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="dashboard" element={<RoleDashboard />} />
        <Route path="patients" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><PatientList /></ProtectedRoute>} />
        <Route path="patients/new" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><PatientNew /></ProtectedRoute>} />
        <Route path="patients/:id/*" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><PatientDetail /></ProtectedRoute>} />
        <Route path="alerts" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><Alerts /></ProtectedRoute>} />
        <Route path="reports" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><HcwReports /></ProtectedRoute>} />

        <Route path="admin/users" element={<ProtectedRoute roles={['ADMIN']}><AdminUsers /></ProtectedRoute>} />
        <Route path="admin/models" element={<ProtectedRoute roles={['ADMIN']}><AdminModels /></ProtectedRoute>} />
        <Route path="admin/knowledge" element={<ProtectedRoute roles={['ADMIN']}><AdminKnowledge /></ProtectedRoute>} />
        <Route path="admin/audit" element={<ProtectedRoute roles={['ADMIN']}><AdminAudit /></ProtectedRoute>} />
      </Route>

      <Route path="*" element={<Navigate to="/app/dashboard" replace />} />
    </Routes>
  )
}
