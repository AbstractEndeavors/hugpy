import { useMemo, useState, useCallback, Fragment } from 'react'

import './ModelTable.css'

function fmtCtx(n) {
  if (n == null) return '?'
  n = Number(n)
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

function modelSearchText(m) {
  return [
    m.key,
    m.name,
    m.hub_id,
    m.framework,
    modelTask(m),
    m.status,
    ...(Array.isArray(m.tasks) ? m.tasks : []),
    ...(Array.isArray(m.tags) ? m.tags : []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function modelFramework(m) {
  return m.framework ?? ''
}

function modelStatus(m) {
  return m.status ?? 'missing'
}
function modelTask(m) {
  return (
    m.primary_task ??
    m.task ??
    m.pipeline_tag ??
    m.pipelineTag ??
    m.tags?.find?.(t => [
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
    ].includes(t)) ??
    m.tasks?.[0] ??
    'unknown'
  )
}


function StatusBadge({ status }) {
  if (status === 'installed') return <span className="badge badge-green">✓ ready</span>
  if (status === 'partial') return <span className="badge badge-yellow">◐ partial</span>
  return <span className="badge badge-red">✗ missing</span>
}

function DownloadProgress({ job, onCancel }) {
  const pct = Math.round((job.progress ?? 0) * 100)
  const indeterminate = job.status === 'running' && !job.total_bytes
  const active = job.status === 'running' || job.status === 'queued'

  return (
    <div className="mt-dl">
      <div className={`mt-dl-bar ${indeterminate ? 'mt-dl-indet' : ''} mt-dl-${job.status}`}>
        <div className="mt-dl-fill" style={{ width: indeterminate ? '40%' : `${pct}%` }} />
      </div>

      <span className="mt-dl-label">
        {job.status === 'queued' && 'queued…'}
        {job.status === 'running' && (
          indeterminate
            ? `downloading… ${fmtBytes(job.downloaded_bytes)}`
            : `${pct}% · ${fmtBytes(job.downloaded_bytes)} / ${fmtBytes(job.total_bytes)}`
        )}
        {job.status === 'failed' && `✗ ${job.error ?? 'failed'}`}
        {job.status === 'cancelled' && 'cancelled'}
      </span>

      {active && (
        <button className="mt-dl-cancel" onClick={() => onCancel(job.id)} title="Cancel download">
          ✕
        </button>
      )}
    </div>
  )
}

const COLUMNS = [
  { key: 'index', label: '#', type: 'num', get: (_m, i) => i + 1 },
  { key: 'name', label: 'Name', type: 'str', get: m => m.name ?? m.key ?? '' },
  { key: 'framework', label: 'Framework', type: 'str', get: m => modelFramework(m) },
  { key: 'task', label: 'Task', type: 'str', get: m => modelTask(m) },
  { key: 'ctx', label: 'Ctx', type: 'num', get: m => Number(m.model_max_length ?? -1) },
  { key: 'status', label: 'Status', type: 'str', get: m => modelStatus(m) },
]

export default function ModelTable({
  models,
  jobsByModel,
  activeChat,
  onDownload,
  onChat,
  onDelete,
  onCancel,
}) {
  const [openKey, setOpenKey] = useState(null)

  const [query, setQuery] = useState('')
  const [frameworkFilter, setFrameworkFilter] = useState('')
  const [taskFilter, setTaskFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sortKey, setSortKey] = useState('name')
  const [sortDir, setSortDir] = useState('asc')
  const [detailKey, setDetailKey] = useState(null)
  const CHATTABLE = new Set(['text-generation', 'image-text-to-text'])
  const isChattable = (m) => CHATTABLE.has(modelTask(m))

  const frameworks = useMemo(() => {
    return [...new Set(models.map(modelFramework).filter(Boolean))].sort()
  }, [models])

  const tasks = useMemo(() => {
    return [...new Set(models.map(modelTask).filter(Boolean))].sort()
  }, [models])

  const statuses = useMemo(() => {
    return [...new Set(models.map(modelStatus).filter(Boolean))].sort()
  }, [models])

  const visibleModels = useMemo(() => {
    const q = query.trim().toLowerCase()

    const filtered = models.filter(m => {
      if (q && !modelSearchText(m).includes(q)) return false
      if (frameworkFilter && modelFramework(m) !== frameworkFilter) return false
      if (taskFilter && modelTask(m) !== taskFilter) return false
      if (statusFilter && modelStatus(m) !== statusFilter) return false
      return true
    })

    const col = COLUMNS.find(c => c.key === sortKey)
    if (!col) return filtered

    return [...filtered].sort((a, b) => {
      const av = col.get(a, 0)
      const bv = col.get(b, 0)

      let cmp
      if (col.type === 'num') {
        cmp = Number(av) - Number(bv)
      } else {
        cmp = String(av).localeCompare(String(bv))
      }

      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [models, query, frameworkFilter, taskFilter, statusFilter, sortKey, sortDir])

  const toggleSort = useCallback((key) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'ctx' ? 'desc' : 'asc')
    }
  }, [sortKey])

  const clearFilters = useCallback(() => {
    setQuery('')
    setFrameworkFilter('')
    setTaskFilter('')
    setStatusFilter('')
  }, [])

  const close = () => setOpenKey(null)

  if (!models.length) {
    return <div className="empty">No models available.</div>
  }
// fields we want shown first, in this order, with a label + formatter
const DETAIL_FIELDS = [
  ['hub_id',           'Hub ID',        v => v],
  ['key',              'Model key',     v => v],
  ['framework',        'Framework',     v => v],
  ['primary_task',     'Primary task',  v => v],
  ['tasks',            'Tasks',         v => (Array.isArray(v) ? v.join(', ') : v)],
  ['model_max_length', 'Context',       v => fmtCtx(v)],
  ['status',           'Status',        v => v],
  ['folder',           'Folder',        v => v],
  ['filename',         'Filename',      v => v],
  ['parameter_count',  'Parameters',    v => (v == null ? null : Number(v).toLocaleString())],
  ['license',          'License',       v => v],
  ['languages',        'Languages',     v => (Array.isArray(v) ? v.join(', ') : v)],
]

const SHOWN_KEYS = new Set(DETAIL_FIELDS.map(([k]) => k))

function ModelDetail({ model, colSpan }) {
  // declared fields that actually have a value
  const rows = DETAIL_FIELDS
    .map(([k, label, fmt]) => [label, fmt(model[k])])
    .filter(([, val]) => val != null && val !== '' && !(Array.isArray(val) && !val.length))

  // anything discovery included that we didn't explicitly list
  const extras = Object.entries(model)
    .filter(([k, v]) =>
      !SHOWN_KEYS.has(k) &&
      v != null && v !== '' &&
      typeof v !== 'object'        // skip nested blobs; see note below
    )

  return (
    <tr className="mt-detail-row">
      <td colSpan={colSpan}>
        <div className="mt-detail">
          <div className="mt-detail-grid">
            {rows.map(([label, val]) => (
              <div className="mt-detail-item" key={label}>
                <span className="mt-detail-label">{label}</span>
                <span className="mt-detail-value">{String(val)}</span>
              </div>
            ))}
          </div>

          {model.tags?.length > 0 && (
            <div className="mt-detail-tags">
              {model.tags.map(t => <span className="mt-detail-tag" key={t}>{t}</span>)}
            </div>
          )}

          {extras.length > 0 && (
            <details className="mt-detail-raw">
              <summary>Other fields ({extras.length})</summary>
              <div className="mt-detail-grid">
                {extras.map(([k, v]) => (
                  <div className="mt-detail-item" key={k}>
                    <span className="mt-detail-label">{k}</span>
                    <span className="mt-detail-value">{String(v)}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      </td>
    </tr>
  )
}
  return (
    <div className="model-table-panel">
      <div className="model-table-filters">
        <span className="model-table-filter-label">Local models</span>

        <input
          className="model-table-search"
          placeholder="filter by name, repo, task, framework…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />

        <select value={frameworkFilter} onChange={e => setFrameworkFilter(e.target.value)}>
          <option value="">Any framework</option>
          {frameworks.map(f => <option key={f} value={f}>{f}</option>)}
        </select>

        <select value={taskFilter} onChange={e => setTaskFilter(e.target.value)}>
          <option value="">Any task</option>
          {tasks.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">Any status</option>
          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        <button className="btn-clear-filters" type="button" onClick={clearFilters}>
          clear
        </button>

        <span className="model-table-count">
          {visibleModels.length} / {models.length}
        </span>
      </div>

      <div className="table-wrap">
        {openKey && <div className="menu-backdrop" onClick={close} />}

        {visibleModels.length === 0 ? (
          <div className="empty">No models match the current filters.</div>
        ) : (
          <table className="model-table">
            <thead>
              <tr>
                {COLUMNS.map(c => (
                  <th
                    key={c.key}
                    className="mt-sortable"
                    onClick={() => toggleSort(c.key)}
                    title={`Sort by ${c.label}`}
                  >
                    {c.label}
                    {sortKey === c.key && (
                      <span className="mt-sort-arrow">
                        {sortDir === 'asc' ? ' ▲' : ' ▼'}
                      </span>
                    )}
                  </th>
                ))}
                <th>Actions</th>
              </tr>
            </thead>

            <tbody>
              {visibleModels.map((m, i) => {
              const rowKey = m.key ?? m.hub_id ?? m.name ?? `model-${i}`
              const modelKey = m.key ?? rowKey

              const job = jobsByModel?.[modelKey] ?? jobsByModel?.[rowKey]
              const isActive = modelKey === activeChat || rowKey === activeChat
              const downloading = job && (job.status === 'queued' || job.status === 'running')
              const installed = m.status === 'installed'
              const onDisk = installed || m.status === 'partial'
              const dlLabel = installed
                ? '↻ Re-download'
                : m.status === 'partial'
                  ? '⬇ Resume download'
                  : '⬇ Download'

              return (
  <Fragment key={rowKey}>
    <tr className={isActive ? 'row-active' : ''}>
      <td className="col-num">{i + 1}</td>

      <td className="col-name">
        <span className="model-name" title={m.hub_id}>{m.name ?? m.key}</span>
        <span className="hub-id">{m.hub_id}</span>
      </td>

                    <td>
                      <span className={`fw-tag fw-${m.framework}`}>{m.framework}</span>
                    </td>

                    <td className="col-task">{modelTask(m)}</td>

                    <td className="col-ctx">{fmtCtx(m.model_max_length)}</td>

                    <td className="col-status">
                      {downloading ? (
                        <DownloadProgress job={job} onCancel={onCancel} />
                      ) : job?.status === 'failed' ? (
                        <span className="badge badge-red" title={job.error}>✗ failed</span>
                      ) : (
                        <StatusBadge status={m.status} />
                      )}
                    </td>

                    <td className="col-actions">
                      <button
                        className="btn-menu"
                        onClick={() => setOpenKey(openKey === rowKey ? null : rowKey)}
                        title="Actions"
                        aria-haspopup="menu"
                        aria-expanded={openKey === rowKey}
                      >
                        ⋯
                      </button>

                      {openKey === rowKey && (
<div className="actions-menu" role="menu">
  <button
    role="menuitem"
    onClick={() => {
      close()
      setDetailKey(detailKey === rowKey ? null : rowKey)
    }}
  >
    {detailKey === rowKey ? '🔼 Hide details' : 'ℹ️ Details'}
  </button>
                          <button
                            role="menuitem"
                            disabled={!installed || !isChattable(m)}
                            title={
                              !installed
                                ? 'Install model first'
                                : !isChattable(m)
                                  ? 'Not a chat model'
                                  : 'Open chat'
                            }
                            onClick={() => { close(); onChat(modelKey) }}
                          >
                            💬 Chat
                          </button>

                          <button
                            role="menuitem"
                            disabled={downloading}
                            onClick={() => { close(); onDownload(modelKey) }}
                          >
                            {downloading ? '… downloading' : dlLabel}
                          </button>

                          {downloading && (
                            <button
                              role="menuitem"
                              className="menu-danger"
                              onClick={() => { close(); onCancel(job.id) }}
                            >
                              ✕ Cancel download
                            </button>
                          )}

                          <button
                            role="menuitem"
                            className="menu-danger"
                            disabled={!onDisk || downloading}
                            title={onDisk ? 'Remove downloaded files from disk' : 'Nothing downloaded'}
                            onClick={() => { close(); onDelete(modelKey) }}
                          >
                            🗑 Delete files
                          </button>
                        </div>
                      )}
                    </td>
                   </tr>

    {detailKey === rowKey && (
      <ModelDetail model={m} colSpan={COLUMNS.length + 1} />
    )}
  </Fragment>
)
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}