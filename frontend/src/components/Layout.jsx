import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import WorkerAvatar from './WorkerAvatar'
import {
  IconBell, IconBookOpen, IconClipboardList, IconCpu, IconFileText,
  IconLayoutDashboard, IconLayoutGrid, IconUser, IconUserCog, IconUsers,
} from './icons'

const NAV_BY_ROLE = {
  HEALTHCARE_WORKER: [
    { to: '/app/dashboard', label: 'Dashboard', Icon: IconLayoutGrid },
    { to: '/app/patients', label: 'Patients', Icon: IconUsers },
    { to: '/app/alerts', label: 'Risk Alerts', Icon: IconBell },
    { to: '/app/reports', label: 'Reports', Icon: IconFileText },
  ],
  ADMIN: [
    { to: '/app/dashboard', label: 'Dashboard', Icon: IconLayoutGrid },
    { to: '/app/patients', label: 'Patients', Icon: IconUsers },
    { to: '/app/admin/users', label: 'Users', Icon: IconUserCog },
    { to: '/app/admin/models', label: 'Models', Icon: IconCpu },
    { to: '/app/admin/knowledge', label: 'Knowledge Base', Icon: IconBookOpen },
    { to: '/app/admin/audit', label: 'Audit Logs', Icon: IconClipboardList },
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
              <item.Icon className="side-link-icon" /> {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="user-chip">
            {user?.role === 'HEALTHCARE_WORKER' && (
              <WorkerAvatar src={user.photo_url} name={user.full_name || user.username} size={40} />
            )}
            <div>
              <div className="user-name">{user?.full_name || user?.username}</div>
              <div className="user-role">{ROLE_LABELS[user?.role] || user?.role}</div>
            </div>
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
