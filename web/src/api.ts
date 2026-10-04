import { useEffect, useRef } from 'react'
import type { EventItem } from './types'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

type Method = 'GET' | 'POST' | 'DELETE'

/** Same-origin JSON client. Mutating calls carry the CSRF header the server requires. */
export async function api<T>(path: string, method: Method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(method === 'GET' ? {} : { 'X-AICEO-Request': '1' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) window.dispatchEvent(new Event('aiceo:unauthorized'))
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

/** Subscribe to the live event stream (Server-Sent Events). */
export function useEventStream(projectId: string | null, onEvent: (e: EventItem) => void): void {
  const handler = useRef(onEvent)
  handler.current = onEvent
  useEffect(() => {
    const url = projectId ? `/api/stream?project_id=${encodeURIComponent(projectId)}` : '/api/stream'
    const source = new EventSource(url, { withCredentials: true })
    source.onmessage = (msg) => {
      try {
        handler.current(JSON.parse(msg.data) as EventItem)
      } catch {
        /* ignore malformed frames */
      }
    }
    return () => source.close()
  }, [projectId])
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  return `${m}m ${Math.round(seconds % 60)}s`
}
