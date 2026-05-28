import { useState, useEffect, useCallback } from 'react'
import ModelTable from './components/ModelTable'
import ChatPanel from './components/ChatPanel'
import './App.css'

export default function App() {
  const [models, setModels]         = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [activeChat, setActiveChat] = useState(null)   // model key string
  const [filterTask, setFilterTask] = useState('')
  const [jobs, setJobs]             = useState({})     // jobId -> job object

  // ── fetch model list ────────────────────────────────────────────────────
  const refreshModels = useCallback(() => {
    fetch('/api/models')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => { setModels(data); setLoading(false); setError(null) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => { refreshModels() }, [refreshModels])

  // ── poll running jobs ───────────────────────────────────────────────────
  useEffect(() => {
    const active = Object.values(jobs).filter(j => j.status === 'queued' || j.status === 'running')
    if (!active.length) return
    const timer = setInterval(() => {
      active.forEach(j => {
        fetch(`/api/jobs/${j.job_id}`)
          .then(r => r.json())
          .then(updated => {
            setJobs(prev => ({ ...prev, [updated.job_id]: updated }))
            if (updated.status === 'done') refreshModels()
          })
          .catch(() => {})
      })
    }, 1500)
    return () => clearInterval(timer)
  }, [jobs, refreshModels])

  // ── actions ─────────────────────────────────────────────────────────────
  const handleDownload = useCallback((modelKey) => {
    fetch(`/api/models/${encodeURIComponent(modelKey)}/download`, { method: 'POST' })
      .then(r => r.json())
      .then(data => setJobs(prev => ({
        ...prev,
        [data.job_id]: { job_id: data.job_id, model_key: modelKey, status: 'queued', message: '' }
      })))
      .catch(e => alert(`Download failed: ${e.message}`))
  }, [])

  const handleChat = useCallback((modelKey) => { setActiveChat(modelKey) }, [])

  // ── derived state ────────────────────────────────────────────────────────
  const allTasks = [...new Set(models.flatMap(m => m.tasks ?? []))]
  const displayed = filterTask
    ? models.filter(m => (m.tasks ?? []).includes(filterTask))
    : models
  const jobsByModel = {}
  Object.values(jobs).forEach(j => { jobsByModel[j.model_key] = j })

  return (
    <div className="layout">
      <header className="topbar">
        <span className="logo">🤖 LLM Console</span>
        <div className="topbar-right">
          <select value={filterTask} onChange={e => setFilterTask(e.target.value)}>
            <option value="">All tasks</option>
            {allTasks.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button onClick={refreshModels} title="Refresh model list">↻</button>
        </div>
      </header>

      <div className="body">
        <section className="models-pane" data-chat-open={!!activeChat}>
          {loading && <div className="placeholder">Loading models…</div>}
          {error   && <div className="placeholder error">API error: {error}</div>}
          {!loading && !error && (
            <ModelTable
              models={displayed}
              jobsByModel={jobsByModel}
              activeChat={activeChat}
              onDownload={handleDownload}
              onChat={handleChat}
            />
          )}
        </section>

        {activeChat && (
          <ChatPanel
            modelKey={activeChat}
            model={models.find(m => m.key === activeChat)}
            onClose={() => setActiveChat(null)}
          />
        )}
      </div>
    </div>
  )
}
