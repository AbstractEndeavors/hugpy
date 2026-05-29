// Shared fetch helper that always surfaces the API's real message.
//
// Reads the body once as text, then tries to parse it as JSON. If the backend
// returned an error payload ({error|detail|message}) or a non-JSON body (an
// HTML proxy page, an empty response from an unreachable backend, etc.), we
// throw an Error carrying that text — instead of letting `r.json()` blow up
// with the opaque "JSON.parse: unexpected character at line 1 column 1".
export async function fetchJson(url, options) {
  const r = await fetch(url, options)
  const body = await r.text()

  let data
  try {
    data = JSON.parse(body)
  } catch {
    throw new Error(body.trim() || `HTTP ${r.status} (empty response)`)
  }

  if (!r.ok) {
    const msg = data?.error || data?.detail || data?.message
    throw new Error(msg || `HTTP ${r.status}`)
  }
  return data
}

// Normalize a job object from the llm_storage API into the shape the UI uses.
// That API returns { id, status: queued|running|completed|failed, message, error };
// the UI keys jobs by `job_id` and renders queued|running|done|error.
const JOB_STATUS = { completed: 'done', failed: 'error' }

export function normalizeJob(raw) {
  return {
    job_id: raw.job_id ?? raw.id,
    model_key: raw.model_key,
    hub_id: raw.hub_id,
    status: JOB_STATUS[raw.status] ?? raw.status,
    message: raw.message || raw.error || '',
  }
}
