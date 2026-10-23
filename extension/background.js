async function exposeSessionStorageToContentScripts() {
  await chrome.storage.session.setAccessLevel({
    accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS',
  })
}

chrome.runtime.onInstalled.addListener(() => {
  exposeSessionStorageToContentScripts()
})

chrome.runtime.onStartup.addListener(() => {
  exposeSessionStorageToContentScripts()
})

exposeSessionStorageToContentScripts()

const ALLOWED_API_BASES = new Set([
  'http://127.0.0.1:8000/api/v1',
  'http://localhost:8000/api/v1',
])

function isAllowedRequest(path, method, sessionId) {
  const escapedSessionId = String(sessionId).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const routes = [
    ['GET', /^\/teacher\/sessions$/],
    ['GET', new RegExp(`^/sessions/${escapedSessionId}/teacher-snapshot$`)],
    ['POST', new RegExp(`^/sessions/${escapedSessionId}/end$`)],
    ['GET', new RegExp(`^/sessions/${escapedSessionId}/checks$`)],
    ['PATCH', new RegExp(`^/sessions/${escapedSessionId}/clusters/[0-9a-f-]+/status$`, 'i')],
    ['POST', new RegExp(`^/sessions/${escapedSessionId}/clusters/[0-9a-f-]+/checks/generate$`, 'i')],
    ['POST', new RegExp(`^/sessions/${escapedSessionId}/checks/[0-9a-f-]+/approve$`, 'i')],
    ['POST', new RegExp(`^/sessions/${escapedSessionId}/checks/[0-9a-f-]+/close$`, 'i')],
  ]
  return routes.some(([allowedMethod, pattern]) => allowedMethod === method && pattern.test(path))
}

async function callQuestionPulse(path, init = {}) {
  const saved = await chrome.storage.session.get(['apiBaseUrl', 'sessionId', 'teacherToken'])
  const apiBaseUrl = String(saved.apiBaseUrl || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '')
  if (!ALLOWED_API_BASES.has(apiBaseUrl)) {
    throw new Error('api_base_not_allowed')
  }
  const method = String(init.method || 'GET').toUpperCase()
  if (!isAllowedRequest(String(path), method, saved.sessionId || '')) {
    throw new Error('api_path_not_allowed')
  }
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${saved.teacherToken || ''}`,
    },
    body: init.body,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`)
  }
  return payload
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'questionpulse-api') return false
  callQuestionPulse(message.path, message.init)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : 'extension_request_failed',
    }))
  return true
})
