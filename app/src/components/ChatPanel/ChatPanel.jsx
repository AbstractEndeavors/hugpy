import { useState, useRef, useEffect, useCallback } from 'react'
import { fetchJson, uploadFile } from '../../api'
import './ChatPanel.css'

const PLACEHOLDER_CMDS = '/system <text> · /clear · /tokens <N>'

function isVLModel(model) {
  if (!model) return false
  const task = model.primary_task || model.task
  return task === 'image-text-to-text'
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

function stripDataUrl(dataUrl) {
  const i = dataUrl.indexOf(',')
  return i >= 0 ? dataUrl.slice(i + 1) : dataUrl
}

export default function ChatPanel({ modelKey, model, onClose }) {
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [system, setSystem]         = useState('')
  const [maxTokens, setMaxTokens]   = useState(null)   // null = model max (auto-continued)
  const [streaming, setStreaming]   = useState(false)
  const [attachment, setAttachment] = useState(null)   // {name, isImage, dataUrl?, path?, uploading?}
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)
  const fileRef   = useRef(null)

  const vlCapable = isVLModel(model)

  useEffect(() => { inputRef.current?.focus() }, [modelKey])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const onPickFile = useCallback(async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const isImage = file.type.startsWith('image/')
    setAttachment({ name: file.name, isImage, uploading: true })
    try {
      const dataUrl = isImage ? await readFileAsDataURL(file) : null  // preview only
      const res = await uploadFile(file)            // -> { path }
      setAttachment({ name: file.name, isImage, dataUrl, path: res.path })
    } catch (err) {
      alert(`Could not attach file: ${err?.message ?? err}`)
      setAttachment(null)
    }
  }, [])

  const send = useCallback(async () => {
    const text = input.trim()
    const att = attachment
    if ((!text && !att) || streaming || att?.uploading) return
    setInput('')

    if (text === '/clear') { setMessages([]); return }
    if (text.startsWith('/system ')) { setSystem(text.slice(8).trim()); return }
    if (text.startsWith('/tokens ')) {
      const n = parseInt(text.slice(8).trim(), 10)
      if (!isNaN(n)) setMaxTokens(n)
      return
    }

    const userMsg = { role: 'user', content: text }
    if (att) userMsg.attachment = att
    const history = [...messages, userMsg]
    setMessages(history)
    setAttachment(null)
    setStreaming(true)

    const wireMessages = history
      .filter(m => !m.error)                    // never replay failed turns as context
      .map(({ role, content, attachment: a }) => {
        const base = { role, content }
        if (a?.isImage && a.dataUrl) base.images = [stripDataUrl(a.dataUrl)]
        if (a?.path) base.file = a.path
        return base
      })
    const payload = {
      model_key: modelKey,
      prompt: text,
    }
    // Omit max_new_tokens entirely unless the user set one via /tokens — the
    // backend then defaults to the model's full context and auto-continues
    // past it, so responses are never truncated.
    if (maxTokens) payload.max_new_tokens = maxTokens
    if (att?.path) payload.file = att.path
    const modelName = model?.name ?? modelKey
    setMessages(prev => [...prev, { role: 'assistant', content: '', model: modelName }])

    try {
      const resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`)

      const reader = resp.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const evt = JSON.parse(raw)
            if (evt.type === 'status') {
              // Provisioning / continuation progress — show transiently on the
              // assistant bubble; cleared as soon as real tokens arrive.
              const pct = evt.progress != null ? ` ${Math.round(evt.progress * 100)}%` : ''
              setMessages(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, status: `${evt.message || evt.stage || 'working'}${pct}` }
                return copy
              })
            } else if (evt.type === 'token') {
              setMessages(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: last.content + evt.text, status: null }
                return copy
              })
            } else if (evt.type === 'error') {
              setMessages(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: `[Error: ${evt.message}]`, error: true }
                return copy
              })
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      setMessages(prev => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant' && last.content === '') {
          copy[copy.length - 1] = { role: 'assistant', content: `[Error: ${e.message}]`, error: true }
        } else {
          copy.push({ role: 'assistant', content: `[Error: ${e.message}]`, error: true })
        }
        return copy
      })
    } finally {
      setStreaming(false)
    }
  }, [input, attachment, messages, modelKey, system, maxTokens, streaming])

  const onKey = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }, [send])

  return (
    <aside className="chat-panel">
      <div className="chat-header">
        <div className="chat-title">
          <span className="chat-model">{model?.name ?? modelKey}</span>
          <span className="chat-meta">
            {model?.framework} · {model?.primary_task ?? model?.task}
            {system && <span className="system-set" title={system}> · sys</span>}
            {' · '}{maxTokens ? `max ${maxTokens} tok` : 'unbounded (auto-continue)'}
            {vlCapable && <span className="vl-tag" title="vision-language model"> · 🖼 VL</span>}
          </span>
        </div>
        <div className="chat-header-right">
          <button className="btn-clear-chat" onClick={() => setMessages([])} title="Clear conversation" disabled={streaming}>✕ clear</button>
          <button className="btn-close" onClick={onClose} title="Close chat">✕</button>
        </div>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Chat with <strong>{model?.name ?? modelKey}</strong></p>
            <p className="chat-hint">Commands: {PLACEHOLDER_CMDS}</p>
            <p className="chat-hint">Attach a file with 📎{vlCapable ? ' (images supported)' : ''}.</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg msg-${msg.role} ${msg.error ? 'msg-error' : ''}`}>
            <span className="msg-role">
              {msg.role === 'assistant' ? (msg.model ?? 'assistant') : msg.role}
            </span>
            {msg.attachment?.isImage && msg.attachment.dataUrl && (
              <img className="msg-thumb" src={msg.attachment.dataUrl} alt={msg.attachment.name} title={msg.attachment.name} />
            )}
            {msg.attachment && !msg.attachment.isImage && (
              <span className="msg-file" title={msg.attachment.name}>📎 {msg.attachment.name}</span>
            )}
            {msg.status && !msg.content && (
              <div className="msg-status">⏳ {msg.status}</div>
            )}
            <pre className="msg-content">{msg.content}
              {msg.role === 'assistant' && streaming && i === messages.length - 1 && <span className="cursor">▌</span>}
            </pre>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {attachment && (
        <div className="attach-strip">
          {attachment.isImage
            ? <img src={attachment.dataUrl} alt={attachment.name} className="attach-thumb" />
            : <span className="attach-file">📎</span>}
          <span className="attach-name" title={attachment.name}>
            {attachment.name}{attachment.uploading ? ' · uploading…' : ''}
          </span>
          <button className="attach-remove" onClick={() => setAttachment(null)} disabled={streaming} title="Remove attachment">×</button>
        </div>
      )}

      <div className="chat-input-row">
        <input ref={fileRef} type="file" style={{ display: 'none' }} onChange={onPickFile} />
        <button className="btn-attach" onClick={() => fileRef.current?.click()} disabled={streaming} title="Attach file">📎</button>
        <textarea
          ref={inputRef} className="chat-input" rows={3} value={input}
          onChange={e => setInput(e.target.value)} onKeyDown={onKey}
          placeholder="Message… (Enter to send, Shift+Enter for newline)" disabled={streaming}
        />
        <button className="btn-send" onClick={send} disabled={(!input.trim() && !attachment) || streaming || attachment?.uploading}>
          {streaming ? '…' : '↑ Send'}
        </button>
      </div>
    </aside>
  )
}
