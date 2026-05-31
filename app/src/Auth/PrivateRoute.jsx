// src/Auth/PrivateRoute.jsx
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthProvider'

export function PrivateRoute() {
  const { state } = useAuth()
  const location = useLocation()

  if (state.status === 'checking') {
    return <div style={{ padding: 24, color: '#888' }}>Checking session…</div>
  }
  if (state.status === 'authed') {
    return <Outlet />
  }
  // guest → bounce to login, remembering where they were headed
  return <Navigate to="/login" replace state={{ from: location }} />
}