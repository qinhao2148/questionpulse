import assert from 'node:assert/strict'
import fs from 'node:fs'

// The copilot lives in a single content script, so the routing helpers are
// pulled straight out of the shipped source instead of being re-implemented
// here: a copy would pass while the real extension stayed broken.
const sourcePath = process.argv[2] || 'extension/content.js'
const source = fs.readFileSync(sourcePath, 'utf8')

function extract(name) {
  const marker = `  function ${name}(`
  const start = source.indexOf(marker)
  assert.ok(start >= 0, `${name} is missing from content.js`)
  const end = source.indexOf('\n  }\n', start)
  assert.ok(end > start, `${name} is not closed at the expected indentation`)
  return source.slice(start, end + 5)
}

function load(location) {
  const body = `${extract('pageChannelId')}\n${extract('ongoingRooms')}\n${extract('pickLiveClassroom')}\nreturn { pageChannelId, pickLiveClassroom }`
  // eslint-disable-next-line no-new-func
  return new Function('location', body)(location)
}

const watchPage = load({ pathname: '/watch/8655930', search: '' })
assert.equal(watchPage.pageChannelId(), '8655930')
assert.equal(load({ pathname: '/live/8645366', search: '' }).pageChannelId(), '8645366')
assert.equal(load({ pathname: '/watch', search: '?channelId=8620440' }).pageChannelId(), '8620440')
assert.equal(load({ pathname: '/watch', search: '' }).pageChannelId(), '')

const rooms = [
  { id: 'live', title: '数据库实战', status: 'live', polyv_channel_id: '8655930' },
  { id: 'archived', title: 'QuestionPulse 演示课堂', status: 'ended', polyv_channel_id: '8655930' },
  { id: 'other', title: '别的课堂', status: 'ended', polyv_channel_id: '8645366' },
]

// The reported bug: the archived demo classroom is still bound, but the same
// channel now hosts a live classroom, so the copilot has to follow it.
assert.equal(watchPage.pickLiveClassroom(rooms, '8655930')?.id, 'live')

// A live classroom on a different channel must win over a same-channel one
// that already ended.
assert.equal(
  load({ pathname: '/watch/8790000', search: '' }).pickLiveClassroom(
    [
      { id: 'new-live', title: '新课堂', status: 'live', polyv_channel_id: '8790000' },
      { id: 'old', title: '旧课堂', status: 'ended', polyv_channel_id: '8655930' },
    ],
    '8655930',
  )?.id,
  'new-live',
)

// Two live classrooms and no channel match: stay put rather than guess.
assert.equal(
  load({ pathname: '/watch/1111111', search: '' }).pickLiveClassroom(
    [
      { id: 'a', title: 'A', status: 'live', polyv_channel_id: '2222222' },
      { id: 'b', title: 'B', status: 'live', polyv_channel_id: '3333333' },
    ],
    '9999999',
  ),
  null,
)

// A single live classroom is unambiguous.
assert.equal(
  load({ pathname: '/watch/1', search: '' }).pickLiveClassroom(
    [{ id: 'only', title: '唯一', status: 'live', polyv_channel_id: '5555555' }],
    '',
  )?.id,
  'only',
)

assert.equal(watchPage.pickLiveClassroom([], '8655930'), null)
assert.equal(watchPage.pickLiveClassroom(rooms.filter((room) => room.status === 'ended'), '8655930'), null)

// Optional live check: pass a /teacher/sessions dump and the channel the bound
// classroom belongs to, and confirm the copilot would follow the right room.
const fixture = process.argv[3]
if (fixture) {
  const liveRooms = JSON.parse(fs.readFileSync(fixture, 'utf8'))
  const picked = watchPage.pickLiveClassroom(liveRooms, process.argv[4] || '')
  assert.ok(picked, 'expected a live classroom to follow')
  console.log(`Followed live classroom: ${picked.title} (${picked.id})`)
}

console.log('Extension classroom routing behavior passed.')
