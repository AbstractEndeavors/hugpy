// src/Auth/LoginForm.jsx
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthProvider'

export function LoginForm() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from?.pathname || '/'
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(null); setLoading(true)
    const f = new FormData(e.currentTarget)
    try {
      const ok = await signIn(String(f.get('username') || ''), String(f.get('password') || ''))
      if (ok) navigate(from, { replace: true })
      else setErr('Credentials incorrect or sign-in not permitted.')
    } catch { setErr('Login request failed.') }
    finally { setLoading(false) }
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 320, margin: '80px auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <h2>Sign in</h2>
      {err && <div style={{ color: '#f87171' }}>{err}</div>}
      <input name="username" placeholder="Username" autoComplete="username" autoFocus disabled={loading} />
      <input name="password" type="password" placeholder="Password" autoComplete="current-password" disabled={loading} />
      <button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign In'}</button>
    </form>
  )
}
