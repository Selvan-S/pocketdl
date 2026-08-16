export const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8787';
export const EXTENSION_PROTOCOL_HEADER = '0.2';

export function normalizeBackendUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

export async function getBackendUrl(): Promise<string> {
  const stored = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND_URL });
  return normalizeBackendUrl(String(stored.backendUrl));
}
