import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { fetchJson } from '../../api'
import './HFSearch.css'

const TASK_FILTERS = [
  'text-generation', 'image-text-to-text', 'automatic-speech-recognition',
  'feature-extraction', 'summarization', 'text-classification',
  'token-classification', 'fill-mask', 'zero-shot-classification',
  'image-classification', 'object-detection',
]

const LIBRARIES = ['transformers', 'gguf', 'diffusers', 'sentence-transformers', 'timm']

const DEFAULT_TASK = 'text-generation'   // #4: populate this on empty query

function inferFramework(result) {
  const tags = (result.tags || []).map(t => String(t).toLowerCase())
  if (tags.some(t => t.includes('gguf'))) return 'llama_cpp'
  if (result.library_name === 'gguf') return 'llama_cpp'
  if (result.library_name === 'transformers') return 'transformers'
  return 'transformers'
}

function inferTask(result) {
  return result.pipeline_tag || 'text-generation'
}

function fmtCount(n) {
  if (n == null) return '–'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function fmtBytes(n) {
  if (n == null) return '–'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(n), i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${u[i]}`
}

function DownloadBar({ job, onCancel }) {
  if (!job) return null
  const pct = Math.round((job.progress ?? 0) * 100)
  const indeterminate = job.status === 'running' && !job.total_bytes
  const active = job.status === 'running' || job.status === 'queued'
  return (
    <div className="dl-bar-wrap">
      <div className={`dl-bar ${indeterminate ? 'dl-bar-indet' : ''} dl-bar-${job.status}`}>
        <div className="dl-bar-fill" style={{ width: indeterminate ? '40%' : `${pct}%` }} />
      </div>
      <span className="dl-bar-label">
        {job.status === 'queued'    && 'queued…'}
        {job.status === 'running'   && (indeterminate
          ? 'downloading…'
          : `${pct}% · ${fmtBytes(job.downloaded_bytes)} / ${fmtBytes(job.total_bytes)}`)}
        {job.status === 'completed' && '✓ installed'}
        {job.status === 'failed'    && `✗ ${job.error ?? 'failed'}`}
        {job.status === 'cancelled' && 'cancelled'}
      </span>
      {active && (
        <button className="dl-cancel" onClick={() => onCancel(job.id)} title="Cancel download">
          ✕ cancel
        </button>
      )}
    </div>
  )
}

function ResultRow({ r, fw, tk, externallyQueued, job, onJobStarted, onCancelJob }) {
  const [open, setOpen]       = useState(false)
  const [data, setData]       = useState(null)
  const [choice, setChoice]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [adding, setAdding]   = useState(false)

  const expand = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (!next || data || loading) return
    setLoading(true)
    try {
      const d = await fetchJson(`/api/hf/spec?hub_id=${encodeURIComponent(r.hub_id)}`)
      setData(d)
      setChoice(d?.options?.recommended ?? null)
    } catch (e) {
      setData({ error: e.message })
    } finally {
      setLoading(false)
    }
  }, [open, data, loading, r.hub_id])

  const addToLocal = useCallback(async () => {
    const options = data?.options
    if (!options) return
    const opt = options.options.find(o => o.id === choice)
    if (!opt) return
    setAdding(true)
    try {
      const res = await fetchJson('/api/llm/repos/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hub_id: r.hub_id, framework: opt.framework, task: options.task,
          filename: opt.filename ?? null, include: opt.include ?? null,
          total_bytes: opt.total_bytes ?? null, register: true,
        }),
      })
      onJobStarted?.({ ...res, hub_id: r.hub_id })
    } catch (e) {
      alert(`Add failed for ${r.hub_id}: ${e.message}`)
    } finally {
      setAdding(false)
    }
  }, [data, choice, r.hub_id, onJobStarted])

  const options = data?.options
  const selected = options?.options?.find(o => o.id === choice)
  const hasJob = !!job
  const jobActive = hasJob && (job.status === 'queued' || job.status === 'running')

  return (
    <>
      <tr className={open ? 'hf-row-open' : ''}>
        <td className="hf-col-repo">
          <button className="hf-expand" onClick={expand} title="Show install options">
            {open ? '▾' : '▸'}
          </button>
          <a href={`https://huggingface.co/${r.hub_id}`} target="_blank" rel="noreferrer" title={r.hub_id}>
            {r.hub_id}
          </a>
          {r.private && <span className="hf-private" title="private"> 🔒</span>}
        </td>
        <td className="hf-col-task">{tk}</td>
        <td className="hf-col-lib"><span className={`hf-fw fw-${fw}`}>{fw}</span></td>
        <td className="hf-col-num">{fmtBytes(r.total_bytes)}</td>
        <td className="hf-col-num">{fmtCount(r.downloads)}</td>
        <td className="hf-col-num">{fmtCount(r.likes)}</td>
        <td className="hf-col-actions">
          <button className="btn-pull" onClick={expand} disabled={jobActive || externallyQueued}
                  title="Choose an install option">
            {jobActive ? '…' : externallyQueued ? 'queued' : '⬇ Options'}
          </button>
        </td>
      </tr>

      {open && (
        <tr className="hf-spec-row">
          <td colSpan={7}>
            {loading && <span className="hf-spec-loading">Loading specs…</span>}
            {data?.error && <span className="hf-search-error" title={data.error}>{data.error}</span>}
            {options && (
              <div className="hf-options">
                {data.spec && (
                  <div className="hf-spec-meta">
                    {data.spec.context_length != null && <span>ctx {data.spec.context_length}</span>}
                    {data.spec.total_bytes != null && <span>{fmtBytes(data.spec.total_bytes)}</span>}
                    {data.spec.license && <span>{data.spec.license}</span>}
                    {data.spec.gated && <span className="hf-gated">gated</span>}
                  </div>
                )}
                {options.options.length === 0 && <div className="hf-empty">No installable weights found.</div>}
                {options.options.map(o => (
                  <label key={o.id} className={`hf-opt ${o.fits_disk === false ? 'hf-opt-toobig' : ''}`}>
                    <input type="radio" name={`opt-${r.hub_id}`} value={o.id}
                           checked={choice === o.id}
                           disabled={o.fits_disk === false || jobActive}
                           onChange={() => setChoice(o.id)} />
                    {o.label}{o.fits_disk === false && ' · won’t fit'}
                  </label>
                ))}
                {hasJob ? (
                  <DownloadBar job={job} onCancel={onCancelJob} />
                ) : options.options.length > 0 ? (
                  <button className="btn-pull" onClick={addToLocal}
                          disabled={!selected || adding || externallyQueued}
                          title="Download and register this variant">
                    {adding ? '…' : '⬇ Add to local'}
                  </button>
                ) : null}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

const COLUMNS = [
  { key: 'hub_id',     label: 'Repo',  get: r => r.hub_id, type: 'str' },
  { key: 'task',       label: 'Task',  get: r => inferTask(r), type: 'str' },
  { key: 'library',    label: 'Lib',   get: r => inferFramework(r), type: 'str' },
  { key: 'total_bytes',label: 'Size',  get: r => r.total_bytes ?? -1, type: 'num' },
  { key: 'downloads',  label: '↓',     get: r => r.downloads ?? -1, type: 'num' },
  { key: 'likes',      label: '♥',     get: r => r.likes ?? -1, type: 'num' },
]

export default function HFSearch({ onJobStarted, onCancelJob, pendingByHub, jobsByHub, expanded, onToggleExpanded }) {
  const [query, setQuery]     = useState('')
  const [taskFilter, setTask] = useState(DEFAULT_TASK)   // #4: default task
  const [libFilter, setLib]   = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [sortKey, setSortKey] = useState('downloads')    // #3
  const [sortDir, setSortDir] = useState('desc')
  const reqIdRef = useRef(0)

  useEffect(() => {
    const q = query.trim()
    // #4: even with empty q we still search, as long as a task is selected
    if (!q && !taskFilter && !libFilter) { setResults([]); setError(null); return }
    const myReq = ++reqIdRef.current
    setLoading(true)
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ limit: '40' })
      if (q) params.set('q', q)
      if (taskFilter) params.set('task', taskFilter)
      if (libFilter) params.set('library', libFilter)
      fetchJson(`/api/search?${params.toString()}`)
        .then(data => {
          if (myReq !== reqIdRef.current) return
          setResults(Array.isArray(data) ? data : [])
          setError(null)
        })
        .catch(e => {
          if (myReq !== reqIdRef.current) return
          setError(e.message); setResults([])
        })
        .finally(() => { if (myReq === reqIdRef.current) setLoading(false) })
    }, 400)
    return () => clearTimeout(timer)
  }, [query, taskFilter, libFilter])

  const sorted = useMemo(() => {
    const col = COLUMNS.find(c => c.key === sortKey)
    if (!col) return results
    const arr = [...results]
    arr.sort((a, b) => {
      const av = col.get(a), bv = col.get(b)
      let cmp = col.type === 'num' ? av - bv : String(av).localeCompare(String(bv))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return arr
  }, [results, sortKey, sortDir])

  const toggleSort = useCallback((key) => {
    if (sortKey === key) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }, [sortKey])

  return (
    <section className={`hf-search ${expanded ? 'hf-search-expanded' : ''}`}>
      <div className="hf-search-bar">
        <span className="hf-search-label">Search HF</span>
        <input className="hf-search-input" placeholder="filter by name (optional)…"
               value={query} onChange={e => setQuery(e.target.value)} />
        <select value={taskFilter} onChange={e => setTask(e.target.value)}>
          <option value="">Any task</option>
          {TASK_FILTERS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={libFilter} onChange={e => setLib(e.target.value)}>
          <option value="">Any library</option>
          {LIBRARIES.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        {loading && <span className="hf-search-loading">…</span>}
        {error && <span className="hf-search-error" title={error}>!</span>}
        <button className="hf-expand-toggle" onClick={onToggleExpanded}
                title={expanded ? 'Collapse panel' : 'Expand panel'}>
          {expanded ? '⤢ collapse' : '⤢ expand'}
        </button>
      </div>

      {sorted.length > 0 && (
        <div className="hf-results">
          <table className="hf-results-table">
            <thead>
              <tr>
                {COLUMNS.map(c => (
                  <th key={c.key} className="hf-sortable" onClick={() => toggleSort(c.key)}>
                    {c.label}
                    {sortKey === c.key && <span className="hf-sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>}
                  </th>
                ))}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => (
                <ResultRow key={r.hub_id} r={r}
                  fw={inferFramework(r)} tk={inferTask(r)}
                  externallyQueued={pendingByHub?.[r.hub_id]}
                  job={jobsByHub?.[r.hub_id]}
                  onJobStarted={onJobStarted} onCancelJob={onCancelJob} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && sorted.length === 0 && (
        <div className="hf-empty">No matches.</div>
      )}
    </section>
  )
}
