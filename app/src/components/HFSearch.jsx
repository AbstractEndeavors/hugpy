import { useState, useEffect, useRef, useCallback } from 'react'
import './HFSearch.css'

const TASK_FILTERS = [
  '',
  'text-generation',
  'image-text-to-text',
  'automatic-speech-recognition',
  'feature-extraction',
  'summarization',
  'text-classification',
  'token-classification',
  'fill-mask',
  'zero-shot-classification',
  'image-classification',
  'object-detection',
]

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

export default function HFSearch({ onJobStarted, pendingByHub }) {
  const [query, setQuery]       = useState('')
  const [taskFilter, setTask]   = useState('')
  const [results, setResults]   = useState([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [pulling, setPulling]   = useState({})  // hub_id -> bool
  const reqIdRef = useRef(0)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); setError(null); return }
    const myReq = ++reqIdRef.current
    setLoading(true)
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q, limit: '20' })
      if (taskFilter) params.set('task', taskFilter)
      fetch(`/api/search?${params.toString()}`)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json()
        })
        .then(data => {
          if (myReq !== reqIdRef.current) return
          setResults(Array.isArray(data) ? data : [])
          setError(null)
        })
        .catch(e => {
          if (myReq !== reqIdRef.current) return
          setError(e.message)
          setResults([])
        })
        .finally(() => {
          if (myReq !== reqIdRef.current) return
          setLoading(false)
        })
    }, 400)
    return () => clearTimeout(timer)
  }, [query, taskFilter])

  const pull = useCallback(async (result) => {
    if (pulling[result.hub_id]) return
    setPulling(p => ({ ...p, [result.hub_id]: true }))
    try {
      const body = {
        hub_id: result.hub_id,
        framework: inferFramework(result),
        task: inferTask(result),
        register: true,
      }
      const resp = await fetch('/api/llm/repos/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
      const job = await resp.json()
      onJobStarted?.({ ...job, hub_id: result.hub_id })
    } catch (e) {
      alert(`Pull failed for ${result.hub_id}: ${e.message}`)
    } finally {
      setPulling(p => {
        const next = { ...p }
        delete next[result.hub_id]
        return next
      })
    }
  }, [pulling, onJobStarted])

  return (
    <section className="hf-search">
      <div className="hf-search-bar">
        <span className="hf-search-label">Search HF</span>
        <input
          className="hf-search-input"
          placeholder="e.g. qwen vl, llama 3, gguf 7b…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <select value={taskFilter} onChange={e => setTask(e.target.value)}>
          <option value="">Any task</option>
          {TASK_FILTERS.filter(Boolean).map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        {loading && <span className="hf-search-loading">…</span>}
        {error && <span className="hf-search-error" title={error}>!</span>}
      </div>

      {results.length > 0 && (
        <div className="hf-results">
          <table className="hf-results-table">
            <thead>
              <tr>
                <th>Repo</th>
                <th>Task</th>
                <th>Lib</th>
                <th>↓</th>
                <th>♥</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {results.map(r => {
                const fw = inferFramework(r)
                const tk = inferTask(r)
                const isPulling = !!pulling[r.hub_id]
                const externallyQueued = pendingByHub?.[r.hub_id]
                return (
                  <tr key={r.hub_id}>
                    <td className="hf-col-repo">
                      <a
                        href={`https://huggingface.co/${r.hub_id}`}
                        target="_blank"
                        rel="noreferrer"
                        title={r.hub_id}
                      >{r.hub_id}</a>
                      {r.private && <span className="hf-private" title="private"> 🔒</span>}
                    </td>
                    <td className="hf-col-task">{tk}</td>
                    <td className="hf-col-lib">
                      <span className={`hf-fw fw-${fw}`}>{fw}</span>
                    </td>
                    <td className="hf-col-num">{fmtCount(r.downloads)}</td>
                    <td className="hf-col-num">{fmtCount(r.likes)}</td>
                    <td className="hf-col-actions">
                      <button
                        className="btn-pull"
                        onClick={() => pull(r)}
                        disabled={isPulling || externallyQueued}
                        title={`Pull as ${fw} / ${tk}`}
                      >
                        {isPulling ? '…' : externallyQueued ? 'queued' : '⬇ Pull'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {query.trim() && !loading && !error && results.length === 0 && (
        <div className="hf-empty">No matches.</div>
      )}
    </section>
  )
}
