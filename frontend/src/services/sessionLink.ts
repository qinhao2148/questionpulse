const SESSION_QUERY = 'session'
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * The console is a single page, so the open classroom cannot live only in memory:
 * pressing F5 used to drop the teacher back to the list, and there was no link to
 * share. Keeping it in the query string fixes both.
 */
export function readSessionFromUrl(search: string = window.location.search): string {
  const value = new URLSearchParams(search).get(SESSION_QUERY) || ''
  return UUID_PATTERN.test(value) ? value : ''
}

/** Builds the address to show after opening or closing a classroom. */
export function sessionUrl(sessionId: string, currentHref: string = window.location.href): string {
  const url = new URL(currentHref)
  if (sessionId) url.searchParams.set(SESSION_QUERY, sessionId)
  else url.searchParams.delete(SESSION_QUERY)
  return `${url.pathname}${url.search}${url.hash}`
}
