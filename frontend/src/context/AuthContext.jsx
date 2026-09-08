import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { authService } from '../services/auth'
import { tokenStorage } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(true)

  useEffect(() => {
    // Restore session on refresh if a token exists.
    if (tokenStorage.access) {
      authService.profile()
        .then((data) => setUser(data ?? null))
        .catch(() => {
          tokenStorage.access = null
          tokenStorage.refresh = null
        })
        .finally(() => setBooting(false))
    } else {
      setBooting(false)
    }
    const onForcedLogout = () => setUser(null)
    window.addEventListener('aimhra:logout', onForcedLogout)
    return () => window.removeEventListener('aimhra:logout', onForcedLogout)
  }, [])

  const login = useCallback(async (username, password) => {
    const u = await authService.login(username, password)
    setUser(u)
    return u
  }, [])

  const logout = useCallback(async () => {
    await authService.logout()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, setUser, booting, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
