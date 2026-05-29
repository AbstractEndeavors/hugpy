import { useState, useRef, useEffect, useCallback } from 'react'
import { apiUrl } from '../api'
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
    r.onload = () => resolve({ name: file.name, dataUrl: r.result })
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

function stripDataUrl(dataUrl) {
  const i = dataUrl.indexOf(',')
  return i >= 0 ? dataUrl.slice(i + 1) : dataUrl
}

export default function ChatPanel({ modelKey, model, onClose }) {
  const [messages, setMessages]     = useState([])     // {role, content}
  const [input, setInput]           = useState('')
  const [system, setSystem]         = useState('')
  const [maxTokens, setMaxTokens]   = useState(2048)
  const [streaming, setStreaming]   = useState(false)
  const [attachment, setAttachment] = useState(null)   // {name, dataUrl} | null
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)
  const fileRef   = useRef(null)

  const vlCapable = isVLModel(model)

  useEffect(() => { inputRef.current?.focus() }, [modelKey])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => { if (!vlCapable) setAttachment(null) }, [vlCapable])

  const onPickFile = useCallback(async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const att = await readFileAsDataURL(file)
      setAttachment(att)
    } catch (err) {
      alert(`Could not read file: ${err?.message ?? err}`)
    }
  }, [])

  // ── send ────────────────────────────────────────────────────────────────
  const send = useCallback(async () => {
    const text = input.trim()
    if ((!text && !attachment) || streaming) return
    setInput('')

    // slash-commands
    if (text === '/clear') { setMessages([]); return }
    if (text.startsWith('/system ')) { setSystem(text.slice(8).trim()); return }
    if (text.startsWith('/tokens ')) {
      const n = parseInt(text.slice(8).trim(), 10)
      if (!isNaN(n)) setMaxTokens(n)
      return
    }

    const pendingAttachment = attachment
    const userMsg = pendingAttachment
      ? { role: 'user', content: text, attachment: pendingAttachment }
      : { role: 'user', content: text }

    const history = [...messages, userMsg]
    setMessages(history)
    setAttachment(null)
    setStreaming(true)

    const wireMessages = history.map(({ role, content, attachment: att }) => {
      const base = { role, content }
      if (att) base.images = [stripDataUrl(att.dataUrl)]
      return base
    })

    const payload = {
      model_key: modelKey,
      messages: system
        ? [{ role: 'system', content: system }, ...wireMessages]
        : wireMessages,
      max_new_tokens: maxTokens,
    }

    // Add optimistic assistant placeholder
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const resp = await fetch(apiUrl('/chat/stream'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!resp.ok) {
        const err = await resp.text()
        throw new Error(`${resp.status}: ${err}`)
      }

      const reader = resp.body.getReader()
      const dec = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        // Process complete SSE lines
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const evt = JSON.parse(raw)
            if (evt.type === 'token') {
              setMessages(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') {
                  copy[copy.length - 1] = { ...last, content: last.content + evt.text }
                }
                return copy
              })
            } else if (evt.type === 'error') {
              setMessages(prev => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last?.role === 'assistant') {
                  copy[copy.length - 1] = { ...last, content: `[Error: ${evt.message}]`, error: true }
                }
                return copy
              })
            }
          } catch { /* ignore parse errors */ }
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
      {/* header */}
      <div className="chat-header">
        <div className="chat-title">
          <span className="chat-model">{model?.name ?? modelKey}</span>
          <span className="chat-meta">
            {model?.framework} · {model?.primary_task}
            {system && <span className="system-set" title={system}> · sys</span>}
            {' · '}max {maxTokens} tok
            {vlCapable && <span className="vl-tag" title="vision-language model"> · 🖼 VL</span>}
          </span>
        </div>
        <div className="chat-header-right">
          <button
            className="btn-clear-chat"
            onClick={() => setMessages([])}
            title="Clear conversation"
            disabled={streaming}
          >
            ✕ clear
          </button>
          <button className="btn-close" onClick={onClose} title="Close chat">✕</button>
        </div>
      </div>

      {/* messages */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Chat with <strong>{model?.name ?? modelKey}</strong></p>
            <p className="chat-hint">Commands: {PLACEHOLDER_CMDS}</p>
            {vlCapable && <p className="chat-hint">Attach an image with the 📎 button.</p>}
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg msg-${msg.role} ${msg.error ? 'msg-error' : ''}`}>
            <span className="msg-role">{msg.role}</span>
            {msg.attachment && (
              <img
                className="msg-thumb"
                src={msg.attachment.dataUrl}
                alt={msg.attachment.name}
                title={msg.attachment.name}
              />
            )}
            <pre className="msg-content">{msg.content}
              {msg.role === 'assistant' && streaming && i === messages.length - 1 && (
                <span className="cursor">▌</span>
              )}
            </pre>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* attachment preview */}
      {attachment && (
        <div className="attach-strip">
          <img src={attachment.dataUrl} alt={attachment.name} className="attach-thumb" />
          <span className="attach-name" title={attachment.name}>{attachment.name}</span>
          <button
            className="attach-remove"
            onClick={() => setAttachment(null)}
            disabled={streaming}
            title="Remove attachment"
          >×</button>
        </div>
      )}

      {/* input */}
      <div className="chat-input-row">
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={onPickFile}
        />
        <button
          className="btn-attach"
          onClick={() => fileRef.current?.click()}
          disabled={!vlCapable || streaming}
          title={vlCapable ? 'Attach image' : 'Selected model does not accept images'}
        >📎</button>
        <textarea
          ref={inputRef}
          className="chat-input"
          rows={3}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder="Message… (Enter to send, Shift+Enter for newline)"
          disabled={streaming}
        />
        <button
          className="btn-send"
          onClick={send}
          disabled={(!input.trim() && !attachment) || streaming}
        >
          {streaming ? '…' : '↑ Send'}
        </button>
      </div>
    </aside>
  )
}
