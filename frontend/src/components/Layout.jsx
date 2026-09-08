import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const NAV_BY_ROLE = {
  HEALTHCARE_WORKER: [
    { to: '/app/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/app/patients', label: 'Patients', icon: '👥' },
    { to: '/app/alerts', label: 'Risk Alerts', icon: '🔔' },
    { to: '/app/reports', label: 'Reports', icon: '📄' },
  ],
  ADMIN: [
    { to: '/app/dashboard', label: 'Dashboard', icon: '▦' },
    { to: '/app/patients', label: 'Patients', icon: '👥' },
    { to: '/app/admin/users', label: 'Users', icon: '👤' },
    { to: '/app/admin/models', label: 'Models', icon: '🧠' },
    { to: '/app/admin/knowledge', label: 'Knowledge Base', icon: '📚' },
    { to: '/app/admin/audit', label: 'Audit Logs', icon: '🧾' },
  ],
}

const ROLE_LABELS = {
  HEALTHCARE_WORKER: 'Healthcare Worker',
  ADMIN: 'Administrator',
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const nav = NAV_BY_ROLE[user?.role] || []

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
