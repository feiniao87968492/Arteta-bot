import type { ApiResponse } from './types';

const TOKEN_KEY = 'arteta_dashboard_token';

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function readApiResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const body = (await response.json()) as ApiResponse<T>;
  if (!body.ok) {
    throw new Error(body.error?.message || 'API error');
  }
  return body.data as T;
}

export async function apiGet<T>(path: string, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    headers: { Authorization: `Bearer ${getToken()}`, ...headers }
  });
  return readApiResponse<T>(response);
}

export async function apiPost<T>(path: string, payload: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...headers
    },
    body: JSON.stringify(payload)
  });
  return readApiResponse<T>(response);
}

export async function apiPut<T>(path: string, payload: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...headers
    },
    body: JSON.stringify(payload)
  });
  return readApiResponse<T>(response);
}

export async function apiDelete<T>(path: string, payload?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: {
      ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }),
      Authorization: `Bearer ${getToken()}`,
      ...headers
    },
    body: payload === undefined ? undefined : JSON.stringify(payload)
  });
  return readApiResponse<T>(response);
}
