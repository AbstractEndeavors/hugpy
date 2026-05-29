// Centralized API base. Injected at build time via webpack DefinePlugin so
// the same source builds against a local dev proxy and the production
// api.abstractgpt.ai host without code changes.
//
//   dev  (default):  API_BASE unset  → '/api'   (webpack devServer proxies)
//   prod:            API_BASE=https://api.abstractgpt.ai  → absolute
//
// Build prod with: API_BASE=https://api.abstractgpt.ai npm run build
const RAW = (typeof process !== 'undefined' && process.env && process.env.API_BASE) || '/api'

// Strip trailing slash so apiUrl('/foo') doesn't double up.
export const API_BASE = RAW.replace(/\/+$/, '')

export function apiUrl(path) {
  if (!path.startsWith('/')) path = '/' + path
  return `${API_BASE}${path}`
}
