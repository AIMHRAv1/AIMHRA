import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { pendingAssessments, syncQueuedAssessments } from '../services/offlineQueue'
import { assessmentService } from '../services/auth'

const NAV_BY_ROLE = {
  HEALTHCARE_WORKER: [
    { to: '/app/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/app/patients', label: 'Patients', icon: '👥' },
    { to: '/app/assessment', label: 'New Assessment', icon: '＋' },
    { to: '/app/alerts', label: 'Risk Alerts', icon: '🔔' },
    { to: '/app/reports', label: 'Reports', icon: '📄' },
  ],
  ADMIN: [
    { to: '/app/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/app/admin/users', label: 'Users', icon: '👤' },
    { to: '/app/admin/models', label: 'Models', icon: '🧠' },
    { to: '/app/admin/knowledge', label: 'Knowledge Base', icon: '📚' },
    { to: '/app/admin/audit', label: 'Audit Logs', icon: '🧾' },
  ],
}

const ROLE_LABELS = {
  PATIENT: 'Patient',
  HEALTHCARE_WORKER: 'Healthcare Worker',
  ADMIN: 'Administrator',
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const nav = NAV_BY_ROLE[user?.role] || []
  const [online, setOnline] = useState(navigator.onLine)
  const [pending, setPending] = useState(0)

  useEffect(() => {
    async function refresh() {
      if (navigator.onLine) await syncQueuedAssessments((payload) => assessmentService.create(payload))
      setPending((await pendingAssessments()).length)
    }
    const onOnline = () => { setOnline(true); refresh() }
    const onOffline = () => setOnline(false)
    refresh()
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => { window.removeEventListener('online', onOnline); window.removeEventListener('offline', onOffline) }
  }, [])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">✚</span>
          <div>
            <div className="brand-name">AIMHRA</div>
            <div className="brand-sub">Maternal Health DSS</div>
          </div>
        </div>
        <nav className="side-nav">
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `side-link${isActive ? ' active' : ''}`}>
              <span aria-hidden="true">{item.icon}</span> {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          {user?.role === 'HEALTHCARE_WORKER' && <div className="muted small">{online ? 'Online' : 'Offline'} · {pending} pending sync</div>}
          <div className="user-chip">
            <div className="user-name">{user?.full_name || user?.username}</div>
            <div className="user-role">{ROLE_LABELS[user?.role] || user?.role}</div>
          </div>
          <button className="btn btn-ghost btn-block" onClick={handleLogout}>Sign out</button>
        </div>
      </aside>
      <main className="main-area">
        <Outlet />
      </main>
    </div>
  )
}
