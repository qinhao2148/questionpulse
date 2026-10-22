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

  function respond(requestId, ok, error = '') {
    window.postMessage({
      source: 'questionpulse-copilot-extension',
      type: 'QUESTIONPULSE_BIND_RESULT',
      requestId,
      ok,
      error,
    }, window.location.origin)
  }

  window.addEventListener('message', async (event) => {
    if (event.source !== window || !ALLOWED_ORIGINS.has(event.origin)) return
    const message = event.data
    if (message?.source !== 'questionpulse-teacher-app' || message?.type !== 'QUESTIONPULSE_BIND_COPILOT') return

    const requestId = String(message.requestId || '')
    const apiBaseUrl = String(message.payload?.apiBaseUrl || '').replace(/\/$/, '')
    const sessionId = String(message.payload?.sessionId || '')
    const teacherToken = String(message.payload?.teacherToken || '')
    if (!UUID_PATTERN.test(requestId) || !UUID_PATTERN.test(sessionId)
      || !ALLOWED_API_BASES.has(apiBaseUrl) || !/^qpt_[A-Za-z0-9_-]{32,}$/.test(teacherToken)) {
      respond(requestId, false, 'invalid_pairing_payload')
      return
    }

    try {
      await chrome.storage.session.set({ apiBaseUrl, sessionId, teacherToken })
      respond(requestId, true)
    } catch (error) {
      respond(requestId, false, error instanceof Error ? error.message : 'pairing_failed')
    }
  })
})()
