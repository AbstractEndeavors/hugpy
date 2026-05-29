import { useState } from 'react'
import './ModelTable.css'

function fmtCtx(n) {
  if (n == null) return '?'
  n = Number(n)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function StatusBadge({ status }) {
  if (status === 'installed') return <span className="badge badge-green">✓ ready</span>
  if (status === 'partial')   return <span className="badge badge-yellow">◐ partial</span>
  return <span className="badge badge-red">✗ missing</span>
}

function JobBadge({ job }) {
  if (!job) return null
  const map = {
    queued:  ['badge-yellow', '⏳ queued'],
    running: ['badge-blue',   '⬇ downloading…'],
    done:    ['badge-green',  '✓ done'],
    error:   ['badge-red',    '✗ error'],
  }
  const [cls, label] = map[job.status] ?? ['badge-muted', job.status]
  return <span className={`badge ${cls}`}>{label}</span>
}

export default function ModelTable({ models, jobsByModel, activeChat, onDownload, onChat, onDelete }) {
  const [openKey, setOpenKey] = useState(null)

  if (!models.length) {
    return <div className="empty">No models match the current filter.</div>
  }

  const close = () => setOpenKey(null)

  return (
    <div className="table-wrap">
      {openKey && <div className="menu-backdrop" onClick={close} />}
      <table className="model-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Framework</th>
            <th>Task</th>
            <th>Ctx</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m, i) => {
            const job = jobsByModel[m.key]
            const isActive = m.key === activeChat
            const downloading = job && (job.status === 'queued' || job.status === 'running')
            const installed = m.status === 'installed'
            const onDisk = installed || m.status === 'partial'
            const dlLabel = installed ? '↻ Re-download' : m.status === 'partial' ? '⬇ Resume download' : '⬇ Download'
            return (
              <tr key={m.key} className={isActive ? 'row-active' : ''}>
                <td className="col-num">{i + 1}</td>
                <td className="col-name">
                  <span className="model-name" title={m.hub_id}>{m.name ?? m.key}</span>
                  <span className="hub-id">{m.hub_id}</span>
                </td>
                <td>
                  <span className={`fw-tag fw-${m.framework}`}>{m.framework}</span>
                </td>
                <td className="col-task">{m.primary_task ?? m.tasks?.[0] ?? m.task}</td>
                <td className="col-ctx">{fmtCtx(m.model_max_length)}</td>
                <td>
                  {downloading
                    ? <JobBadge job={job} />
                    : <StatusBadge status={m.status} />
                  }
                  {job?.status === 'error' && (
                    <span className="job-error" title={job.message}>!</span>
                  )}
                </td>
                <td className="col-actions">
                  <button
                    className="btn-menu"
                    onClick={() => setOpenKey(openKey === m.key ? null : m.key)}
                    title="Actions"
                    aria-haspopup="menu"
                    aria-expanded={openKey === m.key}
                  >⋯</button>
                  {openKey === m.key && (
                    <div className="actions-menu" role="menu">
                      <button
                        role="menuitem"
                        disabled={!installed}
                        title={installed ? 'Open chat' : 'Install model first'}
                        onClick={() => { close(); onChat(m.key) }}
                      >💬 Chat</button>
                      <button
                        role="menuitem"
                        disabled={downloading}
                        onClick={() => { close(); onDownload(m.key) }}
                      >{downloading ? '… downloading' : dlLabel}</button>
                      <button
                        role="menuitem"
                        className="menu-danger"
                        disabled={!onDisk || downloading}
                        title={onDisk ? 'Remove downloaded files from disk' : 'Nothing downloaded'}
                        onClick={() => { close(); onDelete(m.key) }}
                      >🗑 Delete files</button>
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
