import type { ApiErrorBody, CreateLinkRequest, CreatedLink, LinkStats } from '../types/links';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
  } catch {
    throw new Error('Could not connect to ShortLink. Check your connection and try again.');
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body.error?.message) message = body.error.message;
      else if (typeof body.detail === 'string') message = body.detail;
    } catch {
      // A malformed non-JSON response gets a predictable generic error.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error('ShortLink returned an unreadable response. Please try again.');
  }
}

export function createLink(payload: CreateLinkRequest): Promise<CreatedLink> {
  return request<CreatedLink>('/links', { method: 'POST', body: JSON.stringify(payload) });
}

export function getLinkStats(code: string): Promise<LinkStats> {
  return request<LinkStats>(`/links/${encodeURIComponent(code)}/stats`, { method: 'GET' });
}
