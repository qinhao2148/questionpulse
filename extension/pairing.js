(() => {
  const ALLOWED_ORIGINS = new Set([
    'http://127.0.0.1:5173',
    'http://localhost:5173',
  ])
  const ALLOWED_API_BASES = new Set([
    'http://127.0.0.1:8000/api/v1',
    'http://localhost:8000/api/v1',
  ])
  const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
  const TOKEN_PATTERN = /^qpa_[0-9]{9,12}_[A-Za-z0-9_-]{16,}$/
  // Must match TEACHER_PORTAL_TOKEN_KEY in frontend/src/services/api.ts.
  const PAGE_TOKEN_KEY = 'questionpulse.teacher_portal_token'
  const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1'

  function respond(requestId, ok, error = '') {
    window.postMessage({
      source: 'questionpulse-copilot-extension',
      type: 'QUESTIONPULSE_BIND_RESULT',
      requestId,
      ok,
      error,
    }, window.location.origin)
  }

  function sessionIdFromPath() {
    const match = window.location.pathname.match(/\/teacher\/([0-9a-f-]{36})/i)
    return match ? match[1] : ''
  }

  function pageToken() {
    try {
      const token = window.localStorage.getItem(PAGE_TOKEN_KEY) || ''
      return TOKEN_PATTERN.test(token) ? token : ''
    } catch {
      return ''
    }
  }

  // The teacher console keeps its token in localStorage. Because this content
  // script runs in the console's origin it can read it directly, which means a
  // fresh login propagates to the copilot without the teacher having to click
  // "一键连接开播助手" on the exact page that happens to load us.
  async function syncFromPage() {
    if (!ALLOWED_ORIGINS.has(window.location.origin)) return
    const token = pageToken()
    if (!token) return
    let saved
    try {
      saved = await chrome.storage.session.get(['apiBaseUrl', 'webBaseUrl', 'sessionId', 'teacherToken'])
    } catch {
      return
    }
    const sessionId = sessionIdFromPath()
    const patch = {}
    if (saved.teacherToken !== token) patch.teacherToken = token
    if (saved.webBaseUrl !== window.location.origin) patch.webBaseUrl = window.location.origin
    if (sessionId && saved.sessionId !== sessionId) patch.sessionId = sessionId
    if (!ALLOWED_API_BASES.has(String(saved.apiBaseUrl || ''))) patch.apiBaseUrl = DEFAULT_API_BASE
    if (!Object.keys(patch).length) return
    try {
      await chrome.storage.session.set(patch)
    } catch {
      // A failed write just leaves the old token in place; the manual entry
      // form in the copilot panel remains as the fallback.
    }
  }

  window.addEventListener('message', async (event) => {
    if (event.source !== window || !ALLOWED_ORIGINS.has(event.origin)) return
    const message = event.data
    if (message?.source !== 'questionpulse-teacher-app' || message?.type !== 'QUESTIONPULSE_BIND_COPILOT') return

    const requestId = String(message.requestId || '')
    const apiBaseUrl = String(message.payload?.apiBaseUrl || '').replace(/\/$/, '')
    const webBaseUrl = String(message.payload?.webBaseUrl || '').replace(/\/$/, '')
    const sessionId = String(message.payload?.sessionId || '')
    const teacherToken = String(message.payload?.teacherToken || '')
    if (!UUID_PATTERN.test(requestId) || !UUID_PATTERN.test(sessionId)
      || !ALLOWED_API_BASES.has(apiBaseUrl) || !ALLOWED_ORIGINS.has(webBaseUrl)
      || !TOKEN_PATTERN.test(teacherToken)) {
      respond(requestId, false, 'invalid_pairing_payload')
      return
    }

    try {
      await chrome.storage.session.set({ apiBaseUrl, webBaseUrl, sessionId, teacherToken })
      respond(requestId, true)
    } catch (error) {
      respond(requestId, false, error instanceof Error ? error.message : 'pairing_failed')
    }
  })

  syncFromPage()
  // SPA navigation does not reload this script, so poll the page token rather
  // than waiting for a full page load that may never come.
  setInterval(syncFromPage, 3000)
})()
