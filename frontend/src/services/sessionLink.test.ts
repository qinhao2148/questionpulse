import { describe, expect, it } from 'vitest'

import { readSessionFromUrl, sessionUrl } from './sessionLink'

const SESSION_ID = '2d949747-f1e7-4f4b-8cb3-28b4d019e4b8'
const BASE = 'http://127.0.0.1:5173/'

describe('classroom deep link', () => {
  it('reads a valid classroom id back out of the query string', () => {
    expect(readSessionFromUrl(`?session=${SESSION_ID}`)).toBe(SESSION_ID)
  })

  it('ignores anything that is not a classroom uuid', () => {
    expect(readSessionFromUrl('?session=../etc/passwd')).toBe('')
    expect(readSessionFromUrl('?session=')).toBe('')
    expect(readSessionFromUrl('')).toBe('')
  })

  it('keeps the classroom in the url so a refresh lands on the same class', () => {
    const next = sessionUrl(SESSION_ID, `${BASE}?foo=1#frag`)

    expect(next).toBe(`/?foo=1&session=${SESSION_ID}#frag`)
  })

  it('drops the parameter when the teacher returns to the list', () => {
    expect(sessionUrl('', `${BASE}?session=${SESSION_ID}`)).toBe('/')
  })

  it('replaces an existing classroom instead of appending a second one', () => {
    const next = sessionUrl(SESSION_ID, `${BASE}?session=11111111-1111-1111-1111-111111111111`)
    const parsed = new URL(next, BASE)

    expect(parsed.searchParams.getAll('session')).toEqual([SESSION_ID])
  })
})
