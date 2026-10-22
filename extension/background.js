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

async function callQuestionPulse(path, init = {}) {
  const saved = await chrome.storage.session.get(['apiBaseUrl', 'sessionId', 'teacherToken'])
  const apiBaseUrl = String(saved.apiBaseUrl || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '')
  if (!ALLOWED_API_BASES.has(apiBaseUrl)) {
    throw new Error('api_base_not_allowed')
  }
  if (!String(path).startsWith('/sessions/')) {
    throw new Error('api_path_not_allowed')
  }
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: init.method || 'GET',
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
