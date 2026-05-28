import './ModelTable.css'

function fmtCtx(n) {
  if (n == null) return '?'
  n = Number(n)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function StatusBadge({ installed }) {
  return installed
    ? <span className="badge badge-green">✓ ready</span>
    : <span className="badge badge-red">✗ missing</span>
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

export default function ModelTable({ models, jobsByModel, activeChat, onDownload, onChat }) {
  if (!models.length) {
    return <div className="empty">No models match the current filter.</div>
  }

  return (
    <div className="table-wrap">
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
                <td className="col-task">{m.primary_task}</td>
                <td className="col-ctx">{fmtCtx(m.model_max_length)}</td>
                <td>
                  {downloading
                    ? <JobBadge job={job} />
                    : <StatusBadge installed={m.installed} />
                  }
                  {job?.status === 'error' && (
                    <span className="job-error" title={job.message}>!</span>
                  )}
                </td>
                <td className="col-actions">
                  <button
                    className="btn-dl"
                    onClick={() => onDownload(m.key)}
                    disabled={downloading}
                    title={m.installed ? 'Re-download' : 'Download'}
                  >
                    {m.installed ? '↻' : '⬇'}
                  </button>
                  <button
                    className={`btn-chat ${isActive ? 'btn-chat-active' : ''}`}
                    onClick={() => onChat(m.key)}
                    disabled={!m.installed}
                    title={m.installed ? 'Open chat' : 'Install model first'}
                  >
                    💬 Chat
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
