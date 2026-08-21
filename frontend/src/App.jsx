import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/auth/Login'
import Register from './pages/auth/Register'
import PatientDashboard from './pages/patient/Dashboard'
import Assessment from './pages/patient/Assessment'
import History from './pages/patient/History'
import Chat from './pages/patient/Chat'
import Reports from './pages/patient/Reports'
import Profile from './pages/patient/Profile'
import Settings from './pages/patient/Settings'
import HcwDashboard from './pages/hcw/Dashboard'
import PatientList from './pages/hcw/Patients'
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
  return <PatientDashboard />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Navigate to="/app/dashboard" replace />} />

      <Route path="/app" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="dashboard" element={<RoleDashboard />} />
        <Route path="assessment" element={<ProtectedRoute roles={['PATIENT']}><Assessment /></ProtectedRoute>} />
        <Route path="history" element={<ProtectedRoute roles={['PATIENT']}><History /></ProtectedRoute>} />
        <Route path="chat" element={<ProtectedRoute roles={['PATIENT']}><Chat /></ProtectedRoute>} />
        <Route path="profile" element={<ProtectedRoute roles={['PATIENT']}><Profile /></ProtectedRoute>} />
        <Route path="settings" element={<ProtectedRoute roles={['PATIENT']}><Settings /></ProtectedRoute>} />

        <Route path="patients" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><PatientList /></ProtectedRoute>} />
        <Route path="patients/:id" element={<ProtectedRoute roles={['HEALTHCARE_WORKER', 'ADMIN']}><PatientDetail /></ProtectedRoute>} />
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
