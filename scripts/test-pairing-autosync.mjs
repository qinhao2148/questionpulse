import { readFile } from 'node:fs/promises'
import path from 'node:path'
import vm from 'node:vm'
import assert from 'node:assert/strict'

const projectRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..')
const source = await readFile(path.join(projectRoot, 'extension', 'pairing.js'), 'utf8')
const TOKEN_KEY = 'questionpulse.teacher_portal_token'
const SESSION_ID = '2d949747-f1e7-4f4b-8cb3-28b4d019e4b8'
const GOOD_TOKEN = 'qpa_1792737292_cf695b430e93adb29a07b7cd3cf0ef9cfeca55919f5fa292234eb20aac05675c'

function makeHarness({ path = `/teacher/${SESSION_ID}`, origin = 'http://127.0.0.1:5173', token = GOOD_TOKEN, saved = {} } = {}) {
  const store = { ...saved }
  const intervals = []
  const listeners = {}
  const posted = []
  const localStore = token ? { [TOKEN_KEY]: token } : {}

  const chrome = {
    storage: {
      session: {
        get: async (keys) => Object.fromEntries(keys.filter((key) => key in store).map((key) => [key, store[key]])),
        set: async (patch) => { Object.assign(store, patch) },
      },
    },
  }

  const context = {
    chrome,
    console,
    setTimeout,
    clearTimeout,
    setInterval: (fn) => { intervals.push(fn); return intervals.length },
    clearInterval: () => {},
    localStorage: {
      getItem: (key) => (key in localStore ? localStore[key] : null),
      setItem: (key, value) => { localStore[key] = String(value) },
      removeItem: (key) => { delete localStore[key] },
    },
    location: { origin, pathname: path, search: '' },
    window: {
      location: { origin, pathname: path },
      localStorage: null,
      addEventListener: (type, handler) => { listeners[type] = handler },
      postMessage: (message) => { posted.push(message) },
    },
  }
  context.window.localStorage = context.localStorage
  vm.createContext(context)
  vm.runInContext(source, context)
  return { context, store, listeners, posted, tick: () => Promise.all(intervals.map((fn) => fn())) }
}

// 1. A fresh login in the teacher console propagates without any button press.
{
  const { store } = makeHarness()
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(store.teacherToken, GOOD_TOKEN, 'auto sync must copy the page token')
  assert.equal(store.sessionId, SESSION_ID, 'auto sync must adopt the classroom from the URL')
  assert.equal(store.webBaseUrl, 'http://127.0.0.1:5173')
  assert.equal(store.apiBaseUrl, 'http://127.0.0.1:8000/api/v1')
}

// 2. An already-synced token is not rewritten on every poll.
{
  const { store } = makeHarness({ saved: { teacherToken: GOOD_TOKEN, sessionId: SESSION_ID, webBaseUrl: 'http://127.0.0.1:5173', apiBaseUrl: 'http://127.0.0.1:8000/api/v1' } })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(Object.keys(store).length, 4)
}

// 3. Garbage in localStorage never reaches the extension.
{
  const { store } = makeHarness({ token: 'qpt_legacy_token' })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(store.teacherToken, undefined, 'a non qpa_ token must be ignored')
}

// 4. Polling picks up a login that happens after the script loaded (SPA route change).
{
  const { store, tick, context } = makeHarness({ token: '' })
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.equal(store.teacherToken, undefined)
  context.localStorage.setItem(TOKEN_KEY, GOOD_TOKEN)
  await tick()
  assert.equal(store.teacherToken, GOOD_TOKEN, 'interval must catch a later login')
}

// 5. The explicit pairing message still works end to end.
{
  const { listeners, posted, store, context } = makeHarness({ token: '' })
  const requestId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
  await listeners.message({
    source: context.window,
    origin: 'http://127.0.0.1:5173',
    data: {
      source: 'questionpulse-teacher-app',
      type: 'QUESTIONPULSE_BIND_COPILOT',
      requestId,
      payload: {
        apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
        webBaseUrl: 'http://127.0.0.1:5173',
        sessionId: SESSION_ID,
        teacherToken: GOOD_TOKEN,
      },
    },
  })
  assert.equal(store.teacherToken, GOOD_TOKEN)
  assert.equal(posted.at(-1).ok, true)
  assert.equal(posted.at(-1).requestId, requestId)
}

// 6. A malformed pairing payload is rejected and leaves storage untouched.
{
  const { listeners, posted, store, context } = makeHarness({ token: '' })
  await listeners.message({
    source: context.window,
    origin: 'http://127.0.0.1:5173',
    data: {
      source: 'questionpulse-teacher-app',
      type: 'QUESTIONPULSE_BIND_COPILOT',
      requestId: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
      payload: {
        apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
        webBaseUrl: 'http://127.0.0.1:5173',
        sessionId: SESSION_ID,
        teacherToken: 'qpt_short',
      },
    },
  })
  assert.equal(store.teacherToken, undefined)
  assert.equal(posted.at(-1).ok, false)
  assert.equal(posted.at(-1).error, 'invalid_pairing_payload')
}

// 7. Messages from another origin are ignored entirely.
{
  const { listeners, posted, context } = makeHarness({ token: '' })
  await listeners.message({
    source: context.window,
    origin: 'https://evil.example',
    data: { source: 'questionpulse-teacher-app', type: 'QUESTIONPULSE_BIND_COPILOT', requestId: 'x', payload: {} },
  })
  assert.equal(posted.length, 0)
}

console.log('pairing auto-sync: 7/7 passed')
