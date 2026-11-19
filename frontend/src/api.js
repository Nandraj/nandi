const j = async (r) => {
  if (!r.ok) {
    let m = r.statusText
    try { const d = await r.json(); m = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail) } catch {}
    throw new Error(m)
  }
  return r.json()
}
const json = (method, body) => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) })

export const api = {
  health: () => fetch('/api/health').then(j),
  settings: () => fetch('/api/settings').then(j),
  saveSettings: (s) => fetch('/api/settings', json('PUT', s)).then(j),
  testLlm: (body) => fetch('/api/llm/test', json('POST', body)).then(j),
  projects: () => fetch('/api/projects').then(j),
  project: (id) => fetch(`/api/projects/${id}`).then(j),
  create: (form) => fetch('/api/projects', { method: 'POST', body: form }).then(j),
  remove: (id) => fetch(`/api/projects/${id}`, { method: 'DELETE' }).then(j),
  addRefs: (id, form) => fetch(`/api/projects/${id}/refs`, { method: 'POST', body: form }).then(j),
  delRef: (id, rid) => fetch(`/api/projects/${id}/refs/${rid}`, { method: 'DELETE' }).then(j),
  saveOptions: (id, body) => fetch(`/api/projects/${id}/options`, json('PUT', body)).then(j),
  loras: () => fetch('/api/loras').then(j),
  models: () => fetch('/api/models').then(j),
  enhance: (prompt, kind) => fetch('/api/enhance', json('POST', { prompt, kind })).then(j),
  genScript: (id, feedback = '') => fetch(`/api/projects/${id}/script/generate`, json('POST', { feedback })).then(j),
  saveScript: (id, script) => fetch(`/api/projects/${id}/script`, json('PUT', script)).then(j),
  confirmCharacter: (id) => fetch(`/api/projects/${id}/character/confirm`, { method: 'POST' }).then(j),
  approve: (id) => fetch(`/api/projects/${id}/approve`, { method: 'POST' }).then(j),
  resume: (id) => fetch(`/api/projects/${id}/resume`, { method: 'POST' }).then(j),
  resetChunks: (id, idx) => fetch(`/api/projects/${id}/chunks/${idx}/reset`, { method: 'POST' }).then(j),
  setChunkPrompt: (id, idx, prompt) => fetch(`/api/projects/${id}/chunks/${idx}/prompt`, json('PUT', { prompt })).then(j),
  cancel: (id) => fetch(`/api/projects/${id}/cancel`, { method: 'POST' }).then(j),
}
export const media = (p) => `/media/${p}`
