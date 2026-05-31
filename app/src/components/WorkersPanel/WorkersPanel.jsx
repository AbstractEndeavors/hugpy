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

function SpillBadge({ spill }) {
  if (!spill || !spill.mode) return null
  const free = spill.free_vram_bytes
  const label = spill.mode === 'auto' ? 'autofit' : spill.mode
  return (
    <span className="wp-spill" title="GPU/CPU split mode reported by the worker">
      spill: {label}
      {free != null && <em> · {fmtBytes(free)} VRAM free</em>}
    </span>
  )
}

// A worker row: shows status + GPUs + spill mode, the models it serves, and
// controls to attach the worker's compute to any model from the llmTable —
// with an optional advanced GPU/CPU split override per assignment.
function WorkerRow({ worker, models, onAssign, onUnassign, onRemove }) {
  const [pick, setPick] = useState('')
  const [adv, setAdv]   = useState(false)
  const [spill, setSpill] = useState({ n_gpu_layers: '', gpu_mem_gib: '', cpu_mem_gib: '' })
  const [ping, setPing] = useState(null)   // null | 'checking' | {reachable, error}

  const checkHealth = useCallback(async () => {
    setPing('checking')
    try {
      const r = await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/health`)
      setPing(r)
    } catch (e) {
      setPing({ reachable: false, error: e.message })
    }
  }, [worker.id])

  const assignable = useMemo(() => {
    const assigned = new Set(worker.models || [])
    return models.filter(m => !assigned.has(m.key))
  }, [models, worker.models])

  const nameFor = useCallback(
    key => models.find(m => m.key === key)?.name || key,
    [models],
  )

  // Build the spill override dict from the advanced inputs (empty = autofit).
  const buildSpill = useCallback(() => {
    if (!adv) return null
    const out = {}
    if (spill.n_gpu_layers !== '') out.n_gpu_layers = spill.n_gpu_layers
    if (spill.gpu_mem_gib !== '')  out.gpu_mem_gib = Number(spill.gpu_mem_gib)
    if (spill.cpu_mem_gib !== '')  out.cpu_mem_gib = Number(spill.cpu_mem_gib)
    return Object.keys(out).length ? out : null
  }, [adv, spill])

  return (
    <div className={`wp-worker wp-${worker.status}`}>
      <div className="wp-worker-head">
        <span className="wp-dot" />
        <span className="wp-name">{worker.name}</span>
        <span className="wp-status">{worker.status}</span>
        <span className="wp-url" title={worker.url}>{worker.url}</span>
        <SpillBadge spill={worker.spill} />
        {ping && ping !== 'checking' && (
          <span className={`wp-ping ${ping.reachable ? 'wp-ping-ok' : 'wp-ping-bad'}`}
                title={ping.reachable ? 'central can reach this worker' : (ping.error || 'unreachable')}>
            {ping.reachable ? '✓ reachable' : '✗ unreachable'}
          </span>
        )}
        <button className="wp-ping-btn" title="Ping the worker's /health from central"
                onClick={checkHealth} disabled={ping === 'checking'}>
          {ping === 'checking' ? '…' : 'ping'}
        </button>
        <button className="wp-remove" title="Remove worker" onClick={() => onRemove(worker)}>✕</button>
      </div>

      <GpuChips gpus={worker.gpus} />

      <div className="wp-models">
        <span className="wp-models-label">Serving:</span>
        {(worker.models || []).length === 0 && <span className="wp-none">— nothing assigned —</span>}
        {(worker.models || []).map(key => {
          const warm = (worker.loaded_models || []).includes(key)
          const override = worker.spill_by_model?.[key]
          const title = override
            ? `manual split: ${JSON.stringify(override)}`
            : (warm ? 'loaded on GPU (autofit)' : 'assigned (autofit)')
          return (
            <span key={key} className={`wp-model ${warm ? 'wp-warm' : ''}`} title={title}>
              {warm ? '🔥 ' : ''}{nameFor(key)}{override ? ' ⚙' : ''}
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
          onClick={() => { onAssign(worker, pick, buildSpill()); setPick('') }}
        >
          + Assign GPU
        </button>
        <button className="wp-adv-toggle" onClick={() => setAdv(a => !a)}
                title="Manual GPU/CPU split (default is autofit)">
          {adv ? '▾ split' : '▸ split'}
        </button>
      </div>

      {adv && (
        <div className="wp-spill-form">
          <label title="llama.cpp: layers on GPU. Blank/auto = fit automatically; 0 = CPU only.">
            GPU layers
            <input type="number" placeholder="auto" value={spill.n_gpu_layers}
                   onChange={e => setSpill(s => ({ ...s, n_gpu_layers: e.target.value }))} />
          </label>
          <label title="transformers: per-GPU VRAM budget (GiB)">
            GPU GiB
            <input type="number" step="0.5" placeholder="auto" value={spill.gpu_mem_gib}
                   onChange={e => setSpill(s => ({ ...s, gpu_mem_gib: e.target.value }))} />
          </label>
          <label title="transformers: CPU/RAM budget for spilled layers (GiB)">
            CPU GiB
            <input type="number" step="1" placeholder="auto" value={spill.cpu_mem_gib}
                   onChange={e => setSpill(s => ({ ...s, cpu_mem_gib: e.target.value }))} />
          </label>
          <span className="wp-spill-hint">Blank = autofit. Applies on next load of the assigned model.</span>
        </div>
      )}
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

  const assign = useCallback(async (worker, modelKey, spill) => {
    try {
      const body = { model_key: modelKey }
      if (spill) body.spill = spill
      await fetchJson(`/api/llm/workers/${encodeURIComponent(worker.id)}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
