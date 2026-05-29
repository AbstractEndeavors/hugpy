import { useState } from 'react'
import { fetchJson } from '../api'
import './AddFromHF.css'

const FRAMEWORKS = ['transformers', 'llama_cpp', 'dataset']
const TASKS = [
  'text-generation',
  'image-text-to-text',
  'automatic-speech-recognition',
  'feature-extraction',
  'summarization',
  'text-classification',
  'token-classification',
  'fill-mask',
  'zero-shot-classification',
]

export default function AddFromHF({ onJobStarted }) {
  const [hubId, setHubId]         = useState('')
  const [framework, setFramework] = useState('transformers')
  const [task, setTask]           = useState('text-generation')
  const [filename, setFilename]   = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]         = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!hubId.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const job = await fetchJson('/api/llm/repos/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hub_id: hubId.trim(),
          framework,
          task,
          filename: filename.trim() || null,
          register: true,
        }),
      })
      onJobStarted?.(job)
      setHubId('')
      setFilename('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="add-hf" onSubmit={submit}>
      <span className="add-hf-label">Add from HF</span>
      <input
        className="add-hf-input add-hf-hub"
        placeholder="owner/repo (e.g. Qwen/Qwen2.5-VL-7B-Instruct)"
        value={hubId}
        onChange={e => setHubId(e.target.value)}
        disabled={submitting}
      />
      <select value={framework} onChange={e => setFramework(e.target.value)} disabled={submitting}>
        {FRAMEWORKS.map(f => <option key={f} value={f}>{f}</option>)}
      </select>
      <select value={task} onChange={e => setTask(e.target.value)} disabled={submitting}>
        {TASKS.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
      <input
        className="add-hf-input add-hf-file"
        placeholder="filename (optional, for llama_cpp GGUF)"
        value={filename}
        onChange={e => setFilename(e.target.value)}
        disabled={submitting}
      />
      <button type="submit" disabled={!hubId.trim() || submitting}>
        {submitting ? '…' : 'Pull'}
      </button>
      {error && <span className="add-hf-error" title={error}>!</span>}
    </form>
  )
}
