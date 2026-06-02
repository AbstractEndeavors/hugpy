import { useState, useEffect, useCallback } from 'react'
import { fetchJson } from './../api'
// App.jsx
import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './../Auth/AuthProvider'
import { PrivateRoute } from './../Auth/PrivateRoute'
import { LoginForm } from './../Auth/LoginForm'

import {ModelTable,ChatPanel,HFSearch,PeersBar,WorkersPanel} from './../components';
import './App.css'
export function Console() {
  const [models, setModels]         = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [activeChat, setActiveChat] = useState(null)
  const [filterTask, setFilterTask] = useState('')
  const [jobs, setJobs]             = useState({})     // id -> job (backend Job.to_dict shape)
  const [workers, setWorkers]       = useState([])     // for the model-list "run on worker" submenu

  const refreshModels = useCallback(() => {
    fetchJson('/api/models')
      .then(data => { setModels(data); setLoading(false); setError(null) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const refreshWorkers = useCallback(() => {
    fetchJson('/api/llm/workers')
      .then(data => setWorkers(Array.isArray(data) ? data : []))
      .catch(() => {})
  }, [])

  useEffect(() => { refreshModels() }, [refreshModels])
  useEffect(() => {
    refreshWorkers()
    const t = setInterval(refreshWorkers, 10_000)
    return () => clearInterval(t)
  }, [refreshWorkers])

  // Assign a model to a worker from the model list (one-click).
  const assignWorker = useCallback((worker, modelKey) => {
    fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_key: modelKey }),
    }).then(refreshWorkers).catch(e => alert(`Assign failed: ${e.message}`))
  }, [refreshWorkers])

  // Live VRAM-fit probe: load the model on the worker's GPU, report fit.
  const probeWorker = useCallback(async (worker, modelKey) => {
    try {
      return await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/probe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_key: modelKey }),
      })
    } catch (e) {
      return { ok: false, fit: false, error: e.message }
    }
  }, [])

  // poll any active job; backend Job uses `id` + status completed/failed/cancelled
  useEffect(() => {
    const active = Object.values(jobs).filter(j => j.status === 'queued' || j.status === 'running')
    if (!active.length) return
    const timer = setInterval(() => {
      active.forEach(j => {
        fetchJson(`/api/jobs/${j.id}`)
          .then(updated => {
            setJobs(prev => ({ ...prev, [updated.id]: { ...prev[updated.id], ...updated } }))
            if (updated.status === 'completed') refreshModels()
          })
          .catch(() => {})
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [jobs, refreshModels])

  // registered-model download: POST returns Job.to_dict() (has `id`, no model_key in body — we know it)
  const handleDownload = useCallback((modelKey) => {
    fetchJson(`/api/models/${encodeURIComponent(modelKey)}/download`, { method: 'POST' })
      .then(job => setJobs(prev => ({
        ...prev,
        [job.id]: { ...job, model_key: job.model_key ?? modelKey },
      })))
      .catch(e => alert(`Download failed: ${e.message}`))
  }, [])

  const handleChat = useCallback((modelKey) => { setActiveChat(modelKey) }, [])

  const handleDelete = useCallback((modelKey) => {
    if (!confirm(`Delete downloaded files for ${modelKey}?`)) return
    fetchJson(`/api/models/${encodeURIComponent(modelKey)}`, { method: 'DELETE' })
      .then(() => refreshModels())
      .catch(e => alert(`Delete failed: ${e.message}`))
  }, [refreshModels])

  const cancelJob = useCallback((jobId) => {
    fetchJson(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
      .then(() => {
        setJobs(prev => prev[jobId]
          ? { ...prev, [jobId]: { ...prev[jobId], status: 'cancelled' } }
          : prev)
      })
      .catch(e => alert(`Cancel failed: ${e.message}`))
  }, [])

  // freeform /llm/repos/download returns {...Job.to_dict(), model_key}; HFSearch tags hub_id
  const handleHFJobStarted = useCallback((rawJob) => {
    const jobId = rawJob.id ?? rawJob.job_id
    if (!jobId) return
    setJobs(prev => ({
      ...prev,
      [jobId]: {
        ...rawJob,
        id: jobId,
        model_key: rawJob.model_key,
        hub_id: rawJob.hub_id,
        status: rawJob.status ?? 'queued',
      },
    }))
    refreshModels()
  }, [refreshModels])

  // derived
  const allTasks = [...new Set(models.flatMap(m => m.tasks ?? []))]
  const displayed = filterTask
    ? models.filter(m => (m.tasks ?? []).includes(filterTask))
    : models

  const jobsByModel = {}
  Object.values(jobs).forEach(j => { if (j.model_key) jobsByModel[j.model_key] = j })

  const jobsByHub = {}
  Object.values(jobs).forEach(j => { if (j.hub_id) jobsByHub[j.hub_id] = j })

  const pendingByHub = {}
  Object.values(jobs).forEach(j => { if (j.hub_id) pendingByHub[j.hub_id] = true })
  models.forEach(m => { if (m.hub_id && m.status === 'installed') pendingByHub[m.hub_id] = true })

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

      <PeersBar />
      <WorkersPanel models={models} />
      <HFSearch
        onJobStarted={handleHFJobStarted}
        onCancelJob={cancelJob}
        pendingByHub={pendingByHub}
        jobsByHub={jobsByHub}
      />
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
              onDelete={handleDelete}
              onCancel={cancelJob}
              workers={workers}
              onAssignWorker={assignWorker}
              onProbeWorker={probeWorker}
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




export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginForm />} />
        <Route element={<PrivateRoute />}>
          <Route path="/*" element={<Console />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}