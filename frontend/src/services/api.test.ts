import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createClassroom,
  fetchHealth,
  fetchTeacherClassrooms,
  getStudentParticipant,
  hasTeacherAccess,
  listStudentClassrooms,
  loginTeacher,
  logoutTeacher,
  rememberStudentClassroom,
} from './api'

function createStorage(): Storage {
  const entries = new Map<string, string>()
  return {
    get length() {
      return entries.size
    },
    clear: () => entries.clear(),
    getItem: (key: string) => entries.get(key) ?? null,
    key: (index: number) => [...entries.keys()][index] ?? null,
    removeItem: (key: string) => {
      entries.delete(key)
    },
    setItem: (key: string, value: string) => {
      entries.set(key, String(value))
    },
  }
}

function jsonResponse(body: unknown, statusCode = 200): Response {
  return new Response(JSON.stringify(body), {
    status: statusCode,
    headers: { 'Content-Type': 'application/json' },
  })
}

function headersOf(call: unknown[]): Record<string, string> {
  const init = call[1] as RequestInit | undefined
  return (init?.headers ?? {}) as unknown as Record<string, string>
}

beforeEach(() => {
  vi.stubGlobal('localStorage', createStorage())
  vi.stubGlobal('sessionStorage', createStorage())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('teacher portal session', () => {
  it('stores the token on login and clears it on logout', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ data: { access_token: 'qpa_1700000000_abc' } })),
    )

    expect(hasTeacherAccess()).toBe(false)
    await loginTeacher('0', '123456')
    expect(hasTeacherAccess()).toBe(true)

    logoutTeacher()
    expect(hasTeacherAccess()).toBe(false)
  })

  it('sends the bearer token and json content type on teacher requests', async () => {
    localStorage.setItem('questionpulse.teacher_portal_token', 'qpa_1700000000_abc')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await fetchTeacherClassrooms()

    const headers = headersOf(fetchMock.mock.calls[0])
    expect(headers.Authorization).toBe('Bearer qpa_1700000000_abc')
    expect(headers['Content-Type']).toBe('application/json')
  })
})

describe('local classroom history', () => {
  it('keeps one record per classroom with the newest first', () => {
    rememberStudentClassroom('session-a', '第一节')
    rememberStudentClassroom('session-b', '第二节')
    rememberStudentClassroom('session-a', '第一节改名')

    const records = listStudentClassrooms()
    expect(records.map((record) => record.id)).toEqual(['session-a', 'session-b'])
    expect(records[0].title).toBe('第一节改名')
  })

  it('caps stored history at thirty entries', () => {
    for (let index = 0; index < 35; index += 1) {
      rememberStudentClassroom(`session-${index}`, `课堂 ${index}`)
    }

    const records = listStudentClassrooms()
    expect(records).toHaveLength(30)
    expect(records[0].id).toBe('session-34')
  })

  it('returns an empty list when storage holds invalid json', () => {
    localStorage.setItem('questionpulse.student_classrooms', '{not json')
    expect(listStudentClassrooms()).toEqual([])
  })

  it('returns an empty participant string for an unknown classroom', () => {
    expect(getStudentParticipant('missing')).toBe('')
  })
})

describe('error messages', () => {
  it('maps a known backend detail to readable Chinese', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'session_ended' }, 409)),
    )
    await expect(createClassroom('复习课')).rejects.toThrow('课堂已结束')
  })

  it('maps unknown server failures to a retry hint', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'boom' }, 500)))
    await expect(createClassroom('复习课')).rejects.toThrow('课堂服务暂时不可用，请稍后重试')
  })

  it('falls back to a generic hint when the body is not json', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 400 })))
    await expect(createClassroom('复习课')).rejects.toThrow('请求未完成，请检查入口后重试')
  })
})

describe('health probe', () => {
  it('calls the live health endpoint and returns the payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ status: 'ok', service: 'QuestionPulse API', environment: 'development' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const health = await fetchHealth()

    expect(health.status).toBe('ok')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/health/live')
  })
})
