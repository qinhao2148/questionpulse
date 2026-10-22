import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const pairingPath = process.argv[2]
if (!pairingPath) throw new Error('pairing script path is required')
const source = await readFile(pairingPath, 'utf8')

function createHarness() {
  const listeners = new Map()
  const posted = []
  const stored = []
  const window = {
    location: { origin: 'http://127.0.0.1:5173' },
    addEventListener(type, listener) { listeners.set(type, listener) },
    postMessage(message, targetOrigin) { posted.push({ message, targetOrigin }) },
  }
  const chrome = {
    storage: {
      session: {
        async set(value) { stored.push(value) },
      },
    },
  }
  vm.runInNewContext(source, { window, chrome, Set, String, Error }, { filename: pairingPath })
  const listener = listeners.get('message')
  assert.equal(typeof listener, 'function', 'pairing listener must be registered')
  return { window, listener, posted, stored }
}

function validMessage() {
  return {
    source: 'questionpulse-teacher-app',
    type: 'QUESTIONPULSE_BIND_COPILOT',
    requestId: '11111111-1111-4111-8111-111111111111',
    payload: {
      apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
      sessionId: '22222222-2222-4222-8222-222222222222',
      teacherToken: `qpt_${'A'.repeat(40)}`,
    },
  }
}

{
  const harness = createHarness()
  await harness.listener({
    source: harness.window,
    origin: 'http://127.0.0.1:5173',
    data: validMessage(),
  })
  assert.equal(harness.stored.length, 1)
  assert.equal(harness.stored[0].apiBaseUrl, validMessage().payload.apiBaseUrl)
  assert.equal(harness.stored[0].sessionId, validMessage().payload.sessionId)
  assert.equal(harness.stored[0].teacherToken, validMessage().payload.teacherToken)
  assert.equal(harness.posted.length, 1)
  assert.equal(harness.posted[0].message.ok, true)
  assert.equal(harness.posted[0].targetOrigin, 'http://127.0.0.1:5173')
}

{
  const harness = createHarness()
  await harness.listener({
    source: harness.window,
    origin: 'https://attacker.example',
    data: validMessage(),
  })
  assert.equal(harness.stored.length, 0)
  assert.equal(harness.posted.length, 0)
}

{
  const harness = createHarness()
  const message = validMessage()
  message.payload.apiBaseUrl = 'https://attacker.example/api/v1'
  await harness.listener({
    source: harness.window,
    origin: 'http://127.0.0.1:5173',
    data: message,
  })
  assert.equal(harness.stored.length, 0)
  assert.equal(harness.posted[0].message.ok, false)
  assert.equal(harness.posted[0].message.error, 'invalid_pairing_payload')
}

console.log('Extension pairing behavior passed.')
