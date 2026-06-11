import { useEffect, useState, useCallback } from 'react'
import { fetchJson } from '../../api'
import { useAuth } from '../../Auth/AuthProvider'
import './SharedQueuePanel.css'

// Shared shard queue: one queue for everyone signed into the console.
// Prompts go to /api/shard-queue; a server-side dispatcher feeds them to
// the deployment's /v1 chat endpoint one at a time, so the allocator /
// shard pool decides which clustered GPUs actually run each job.

function JobRow({ job, onCancel, onRemove }) {
  const [open, setOpen] = useState(false)
  const expandable = (job.status === 'done' && job.result != null) || job.status === 'error'
  const dur = job.started_at && job.finished_at
    ? ` · ${(job.finished_at - job.started_at).toFixed(1)}s` : ''
  return (
    <div className="sqp-job">
      <div className="sqp-job-top">
        <span className={`sqp-chip sqp-${job.status}`}>{job.status}</span>
        <span
          className="sqp-prompt"
          style={expandable ? { cursor: 'pointer' } : undefined}
          title={expandable ? 'click to view result' : job.prompt}
          onClick={() => expandable && setOpen(o => !o)}
        >
          {job.prompt}
        </span>
        {job.status === 'queued' && (
          <button className="sqp-ghost" onClick={() => onCancel(job.id)}>cancel</button>
        )}
        {job.status !== 'queued' && job.status !== 'running' && (
          <button className="sqp-ghost" onClick={() => onRemove(job.id)}>remove</button>
        )}
      </div>
      <div className="sqp-sub">
        {job.user} · {job.model || 'default model'}{dur}
        {expandable && !open && ' · click prompt to view result'}
      </div>
      {open && job.status === 'error' && (
        <pre className="sqp-result sqp-err">{job.error}</pre>
      )}
      {open && job.status === 'done' && job.result != null && (
        <pre className="sqp-result">{job.result}</pre>
      )}
    </div>
  )
}

export default function SharedQueuePanel({ models }) {
  const { state } = useAuth()
  const username = state.user?.username || 'unknown'
  const [jobs, setJobs] = useState([])
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [collapsed, setCollapsed] = useState(true)

  const refresh = useCallback(() => {
    fetchJson('/api/shard-queue')
      .then(d => setJobs(d.jobs || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  const add = useCallback((ev) => {
    ev.preventDefault()
    const p = prompt.trim()
    if (!p) return
    fetchJson('/api/shard-queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: p, model, user: username }),
    }).then(() => { setPrompt(''); refresh() })
      .catch(e => alert(`Queue failed: ${e.message}`))
  }, [prompt, model, username, refresh])

  const cancel = useCallback((id) => {
    fetchJson(`/api/shard-queue/${id}/cancel`, { method: 'POST' })
      .then(refresh).catch(() => {})
  }, [refresh])

  const remove = useCallback((id) => {
    fetchJson(`/api/shard-queue/${id}`, { method: 'DELETE' })
      .then(refresh).catch(() => {})
  }, [refresh])

  const active = jobs.filter(j => j.status === 'queued' || j.status === 'running').length

  return (
    <section className="sqp">
      <header className="sqp-head" onClick={() => setCollapsed(c => !c)}>
        <span className="sqp-title">⛓ Shared queue</span>
        <span className="sqp-count">
          {active ? `${active} active · ` : ''}{jobs.length} job{jobs.length === 1 ? '' : 's'}
        </span>
        <span className="sqp-fold">{collapsed ? '▸' : '▾'}</span>
      </header>
      {!collapsed && (
        <div className="sqp-body">
          <form className="sqp-form" onSubmit={add}>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="prompt to run on the cluster…"
              rows={2}
            />
            <div className="sqp-form-row">
              <select value={model} onChange={e => setModel(e.target.value)}>
                <option value="">default model</option>
                {(models || []).map(m => (
                  <option key={m.key} value={m.key}>{m.name || m.key}</option>
                ))}
              </select>
              <button type="submit" disabled={!prompt.trim()}>Add to queue</button>
            </div>
          </form>
          {jobs.length === 0 && <div className="sqp-empty">queue is empty</div>}
          {jobs.map(j => (
            <JobRow key={j.id} job={j} onCancel={cancel} onRemove={remove} />
          ))}
        </div>
      )}
    </section>
  )
}
