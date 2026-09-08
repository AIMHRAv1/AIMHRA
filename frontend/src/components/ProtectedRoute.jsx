import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Loading } from './ui'

/** Route guard: requires auth; optionally restricts to specific roles. */
export default function ProtectedRoute({ roles, children }) {
  const { user, booting } = useAuth()
  const location = useLocation()

  if (booting) return <div className="page-center"><Loading label="Restoring session…" /></div>
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  // Only HEALTHCARE_WORKER and ADMIN are valid application roles. A legacy/
  // unexpected role must never reach patient-facing functionality.
  if (!['HEALTHCARE_WORKER', 'ADMIN'].includes(user.role)) {
    return <Navigate to="/login" replace />
  }
  if (roles && !roles.includes(user.role)) {
    // Authenticated but wrong role -> send to their own dashboard.
    return <Navigate to="/app/dashboard" replace />
  }
  return children
}
