import type {
  AnalyzeResponse,
  CaptureDownloadRequest,
  CaptureItem,
  Collection,
  CollectionDownloadRequest,
  CollectionItem,
  DownloadCreateRequest,
  DownloadItem,
  InstagramProfilePreviewRequest,
  InstagramProfilePreviewResponse,
  InstagramSessionStatus,
  ProfileItemPreview,
  SettingsResponse,
  SystemStatus,
} from '../types/api';

const API_BASE = '/api';

// FastAPI error bodies are JSON ({"detail": "message"} for a raised
// HTTPException, {"detail": [{"msg": "...", ...}, ...]} for a pydantic
// validation error) -- without this, every failed request surfaced its raw
// JSON body as the user-facing message instead of the actual text.
export function extractErrorMessage(body: string): string | null {
  if (!body) return null;
  try {
    const parsed: unknown = JSON.parse(body);
    const detail = (parsed as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => (item as { msg?: string })?.msg).filter((msg): msg is string => Boolean(msg));
      if (messages.length > 0) return messages.join('; ');
    }
  } catch {
    // Not JSON -- fall through to the raw body below.
  }
  return body;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(extractErrorMessage(body) || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  listDownloads: () => request<DownloadItem[]>('/downloads'),
  createDownload: (payload: DownloadCreateRequest) => request<DownloadItem>('/downloads', { method: 'POST', body: JSON.stringify(payload) }),
  analyze: (payload: Pick<DownloadCreateRequest, 'url' | 'request_context'>) => request<AnalyzeResponse>('/analyze', { method: 'POST', body: JSON.stringify(payload) }),
  cancelDownload: (id: string) => request<DownloadItem>(`/downloads/${id}/cancel`, { method: 'POST' }),
  deleteDownload: (id: string) => request<{ ok: true }>(`/downloads/${id}`, { method: 'DELETE' }),
  status: () => request<SystemStatus>('/system/status'),
  updateYtDlp: () => request<{ ok: true; version: string | null }>('/system/update/yt-dlp', { method: 'POST' }),
  listCaptures: () => request<CaptureItem[]>('/captures'),
  downloadCapture: (id: string, payload: CaptureDownloadRequest) => request<DownloadItem>(`/captures/${id}/download`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteCapture: (id: string) => request<{ ok: true }>(`/captures/${id}`, { method: 'DELETE' }),
  settings: () => request<SettingsResponse>('/settings'),
  updateSettings: (downloadDirectory: string) => request<SettingsResponse>('/settings', { method: 'PUT', body: JSON.stringify({ download_directory: downloadDirectory }) }),
  resetDownloadDirectory: () => request<SettingsResponse>('/settings/reset-download-directory', { method: 'POST' }),
  openDownloadDirectory: () => request<{ ok: true; download_directory: string }>('/settings/open-download-directory', { method: 'POST' }),

  previewInstagramProfile: (payload: InstagramProfilePreviewRequest) =>
    request<InstagramProfilePreviewResponse>('/instagram/profile/preview', { method: 'POST', body: JSON.stringify(payload) }),
  instagramSessionStatus: () => request<InstagramSessionStatus>('/instagram/session'),
  setInstagramSession: (cookieHeader: string) =>
    request<InstagramSessionStatus>('/instagram/session', { method: 'POST', body: JSON.stringify({ cookie_header: cookieHeader }) }),
  clearInstagramSession: () => request<{ ok: true }>('/instagram/session', { method: 'DELETE' }),

  listCollections: () => request<Collection[]>('/collections'),
  createCollection: (name: string) => request<Collection>('/collections', { method: 'POST', body: JSON.stringify({ platform: 'instagram', name }) }),
  renameCollection: (id: string, name: string) => request<Collection>(`/collections/${id}`, { method: 'PUT', body: JSON.stringify({ name }) }),
  deleteCollection: (id: string) => request<{ ok: true }>(`/collections/${id}`, { method: 'DELETE' }),
  listCollectionItems: (id: string) => request<CollectionItem[]>(`/collections/${id}/items`),
  addCollectionItem: (id: string, preview: ProfileItemPreview) =>
    request<CollectionItem>(`/collections/${id}/items`, { method: 'POST', body: JSON.stringify(preview) }),
  removeCollectionItem: (id: string, itemId: string) => request<{ ok: true }>(`/collections/${id}/items/${itemId}`, { method: 'DELETE' }),
  downloadCollection: (id: string, payload: CollectionDownloadRequest = {}) =>
    request<DownloadItem[]>(`/collections/${id}/download`, { method: 'POST', body: JSON.stringify(payload) }),
};
