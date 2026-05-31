// src/Auth/AuthProvider.jsx
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'

const AUTH_API_BASE = 'https://api.abstractendeavors.com'
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'checking' })

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${AUTH_API_BASE}/me`, {
        method: 'GET', credentials: 'include', headers: { Accept: 'application/json' },
      })
      if (r.ok) { setState({ status: 'authed', user: await r.json() }); return }
      if (r.status === 401 || r.status === 403) setState({ status: 'guest' })
    } catch {
      setState(cur => cur.status === 'checking' ? { status: 'guest' } : cur)
    }
  }, [])

  const signIn = useCallback(async (username, password) => {
    const r = await fetch(`${AUTH_API_BASE}/login`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!r.ok) { setState({ status: 'guest' }); return false }
    await refresh()
    return true
  }, [refresh])

  const signOut = useCallback(async () => {
    try {
      await fetch(`${AUTH_API_BASE}/logout`, {
        method: 'POST', credentials: 'include', headers: { Accept: 'application/json' },
      })
    } finally { setState({ status: 'guest' }) }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <AuthContext.Provider value={{ state, refresh, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}