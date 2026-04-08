import { useState } from 'react'
import { C } from '../constants.js'

export default function Login({ onAuth }) {
  const [mode, setMode] = useState('login')  // 'login' | 'register'
  const [joinMode, setJoinMode] = useState('create') // 'create' | 'join'
  const [form, setForm] = useState({ username: '', email: '', password: '', household_name: '', invite_code: '' })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const BASE = import.meta.env.VITE_API_URL ?? ''

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const url = mode === 'login' ? `${BASE}/auth/login` : `${BASE}/auth/register`
      let body
      if (mode === 'login') {
        body = { email: form.email, password: form.password }
      } else {
        body = {
          username: form.username,
          email: form.email,
          password: form.password,
        }
        if (joinMode === 'join' && form.invite_code.trim()) {
          body.invite_code = form.invite_code.trim()
        } else {
          body.household_name = form.household_name || undefined
        }
      }

      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        let msg = `Server error (${res.status})`
        try {
          const data = await res.json()
          const detail = data.detail
          if (typeof detail === 'string') msg = detail
          else if (Array.isArray(detail)) msg = detail.map(e => e.msg || JSON.stringify(e)).join('; ')
          else if (detail) msg = JSON.stringify(detail)
        } catch { /* response wasn't JSON */ }
        throw new Error(msg)
      }
      const data = await res.json()
      localStorage.setItem('fridge_token', data.access_token)
      localStorage.setItem('fridge_user', JSON.stringify(data.user))
      setForm({ username: '', email: '', password: '', household_name: '', invite_code: '' })
      onAuth(data.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const inp = (field, placeholder, type = 'text', required = true) => (
    <input
      type={type}
      placeholder={placeholder}
      value={form[field]}
      onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
      required={required}
      style={{
        width: '100%', boxSizing: 'border-box',
        background: C.surface2, border: `1px solid ${C.border2}`,
        borderRadius: 8, padding: '10px 14px',
        color: C.text, fontSize: 14, fontFamily: "'Syne', sans-serif",
        outline: 'none',
      }}
    />
  )

  return (
    <div style={{
      minHeight: '100vh', background: C.bg,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 16, padding: '36px 40px', width: 360,
      }}>
        <div style={{ fontWeight: 700, fontSize: 22, color: C.teal, marginBottom: 4 }}>
          FridgeAI
        </div>
        <div style={{ color: C.muted, fontSize: 13, marginBottom: 28 }}>
          {mode === 'login' ? 'Sign in to your account' : 'Create a new account'}
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {mode === 'register' && inp('username', 'Username')}
          {inp('email', 'Email', 'email')}
          {inp('password', 'Password', 'password')}

          {mode === 'register' && (
            <>
              {/* Create vs Join toggle */}
              <div style={{ display: 'flex', gap: 8 }}>
                {[['create', 'New Household'], ['join', 'Join Household']].map(([m, label]) => (
                  <button key={m} type="button" onClick={() => setJoinMode(m)} style={{
                    flex: 1,
                    background: joinMode === m ? C.teal + '22' : 'none',
                    border: `1px solid ${joinMode === m ? C.teal : C.border2}`,
                    color: joinMode === m ? C.teal : C.muted,
                    borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12,
                    fontFamily: "'Syne', sans-serif", fontWeight: joinMode === m ? 700 : 400,
                  }}>{label}</button>
                ))}
              </div>

              {joinMode === 'create' && inp('household_name', 'Household name (optional)', 'text', false)}
              {joinMode === 'join' && inp('invite_code', 'Invite code (6 characters)', 'text', true)}

              {joinMode === 'join' && (
                <div style={{ fontSize: 11, color: C.muted, marginTop: -4 }}>
                  Ask a household member for their invite code
                </div>
              )}
            </>
          )}

          {error && (
            <div style={{
              background: C.critical + '22', border: `1px solid ${C.critical}44`,
              borderRadius: 6, padding: '8px 12px', color: C.critical, fontSize: 13,
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              background: C.teal, color: C.bg, border: 'none',
              borderRadius: 8, padding: '11px', fontFamily: "'Syne', sans-serif",
              fontWeight: 700, fontSize: 14, cursor: loading ? 'default' : 'pointer',
              opacity: loading ? 0.7 : 1, marginTop: 4,
            }}
          >
            {loading ? '...' : mode === 'login' ? 'Sign in' : joinMode === 'join' ? 'Join & Create Account' : 'Create Account'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: C.muted }}>
          {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
          <button
            onClick={() => {
              setMode(m => m === 'login' ? 'register' : 'login')
              setForm({ username: '', email: '', password: '', household_name: '', invite_code: '' })
              setError(null)
              setJoinMode('create')
            }}
            style={{
              background: 'none', border: 'none', color: C.teal,
              cursor: 'pointer', fontFamily: "'Syne', sans-serif",
              fontSize: 13, padding: 0,
            }}
          >
            {mode === 'login' ? 'Register' : 'Sign in'}
          </button>
        </div>
      </div>
    </div>
  )
}
