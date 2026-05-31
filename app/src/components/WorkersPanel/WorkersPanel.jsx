import { useEffect, useState, useCallback, useMemo } from 'react'
import { fetchJson } from '../../api'
import './WorkersPanel.css'

function fmtBytes(n) {
  if (n == null) return '?'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(n), i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${u[i]}`
}

function GpuChips({ gpus }) {
  if (!gpus || !gpus.length) return <span className="wp-nogpu">no GPU reported</span>
  return (
    <div className="wp-gpus">
      {gpus.map((g, i) => (
        <span key={i} className="wp-gpu" title={g.name || ''}>
          🖥 {g.name || `GPU ${g.index ?? i}`}
          {g.memory_free != null && g.memory_total != null && (
            <em> · {fmtBytes(g.memory_free)} / {fmtBytes(g.memory_total)} free</em>
          )}
        </span>
      ))}
    </div>
  )
}

// A worker row: shows status + GPUs, the models it serves, and controls to
// attach the worker's compute to any model from the llmTable.
function WorkerRow({ worker, models, onAssign, onUnassign, onRemove }) {
  const [pick, setPick] = useState('')

  const assignable = useMemo(() => {
    const assigned = new Set(worker.models || [])
    return models.filter(m => !assigned.has(m.key))
  }, [models, worker.models])

  const nameFor = useCallback(
    key => models.find(m => m.key === key)?.name || key,
    [models],
  )

  return (
    <div className={`wp-worker wp-${worker.status}`}>
      <div className="wp-worker-head">
        <span className="wp-dot" />
        <span className="wp-name">{worker.name}</span>
        <span className="wp-status">{worker.status}</span>
        <span className="wp-url" title={worker.url}>{worker.url}</span>
        <button className="wp-remove" title="Remove worker" onClick={() => onRemove(worker)}>✕</button>
      </div>

      <GpuChips gpus={worker.gpus} />

      <div className="wp-models">
        <span className="wp-models-label">Serving:</span>
        {(worker.models || []).length === 0 && <span className="wp-none">— nothing assigned —</span>}
        {(worker.models || []).map(key => {
          const warm = (worker.loaded_models || []).includes(key)
          return (
            <span key={key} className={`wp-model ${warm ? 'wp-warm' : ''}`} title={warm ? 'loaded on GPU' : 'assigned'}>
              {warm ? '🔥 ' : ''}{nameFor(key)}
              <button className="wp-model-x" title="Unassign" onClick={() => onUnassign(worker, key)}>×</button>
            </span>
          )
        })}
      </div>

      <div className="wp-assign-row">
        <select value={pick} onChange={e => setPick(e.target.value)}>
          <option value="">Attach a model from the table…</option>
          {assignable.map(m => <option key={m.key} value={m.key}>{m.name || m.key}</option>)}
        </select>
        <button
          className="wp-assign"
          disabled={!pick}
          onClick={() => { onAssign(worker, pick); setPick('') }}
        >
          + Assign GPU
        </button>
      </div>
    </div>
  )
}

export default function WorkersPanel({ models = [] }) {
  const [workers, setWorkers] = useState([])
  const [error, setError]     = useState(null)
  const [open, setOpen]       = useState(false)
  const [form, setForm]       = useState({ name: '', url: '', models: '' })
  const [busy, setBusy]       = useState(false)

  const load = useCallback(() => {
    fetchJson('/api/llm/workers')
      .then(data => { setWorkers(Array.isArray(data) ? data : []); setError(null) })
      .catch(e => setError(e.message))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10_000)
    return () => clearInterval(t)
  }, [load])

  const register = useCallback(async (e) => {
    e.preventDefault()
    if (!form.name.trim() || !form.url.trim()) return
    setBusy(true)
    try {
      await fetchJson('/api/llm/workers/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(),
          url: form.url.trim(),
          models: form.models.split(',').map(s => s.trim()).filter(Boolean),
        }),
      })
      setForm({ name: '', url: '', models: '' })
      load()
    } catch (err) {
      alert(`Could not register worker: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [form, load])

  const assign = useCallback(async (worker, modelKey) => {
    try {
      await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_key: modelKey }),
      })
      load()
    } catch (err) { alert(`Assign failed: ${err.message}`) }
  }, [load])

  const unassign = useCallback(async (worker, modelKey) => {
    try {
      await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/unassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_key: modelKey }),
      })
      load()
    } catch (err) { alert(`Unassign failed: ${err.message}`) }
  }, [load])

  const remove = useCallback(async (worker) => {
    if (!confirm(`Remove worker ${worker.name} from the pool?`)) return
    try {
      await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}`, { method: 'DELETE' })
      load()
    } catch (err) { alert(`Remove failed: ${err.message}`) }
  }, [load])

  const onlineCount = workers.filter(w => w.status === 'online').length

  return (
    <div className="workers-panel">
      <div className="wp-bar" onClick={() => setOpen(o => !o)}>
        <span className="wp-title">🖧 GPU Workers</span>
        <span className="wp-count">{onlineCount} online / {workers.length} total</span>
        {error && <span className="wp-err" title={error}>registry error</span>}
        <span className="wp-toggle">{open ? '▾' : '▸'}</span>
      </div>

      {open && (
        <div className="wp-body">
          <form className="wp-register" onSubmit={register}>
            <input
              placeholder="worker name (e.g. gpu-box-1)"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            />
            <input
              placeholder="worker URL (e.g. http://10.0.0.5:9100)"
              value={form.url}
              onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
            />
            <input
              placeholder="models to serve (optional, comma-separated keys)"
              value={form.models}
              onChange={e => setForm(f => ({ ...f, models: e.target.value }))}
            />
            <button type="submit" disabled={busy}>+ Add worker</button>
          </form>
          <p className="wp-hint">
            Workers normally self-register by running
            <code> python -m abstract_hugpy.worker_agent --central &lt;this host&gt; </code>
            on the GPU box. Use the form above to add one manually.
          </p>

          {workers.length === 0 && <div className="wp-empty">No workers have joined the pool yet.</div>}
          {workers.map(w => (
            <WorkerRow
              key={w.id}
              worker={w}
              models={models}
              onAssign={assign}
              onUnassign={unassign}
              onRemove={remove}
            />
          ))}
        </div>
      )}
    </div>
  )
}
