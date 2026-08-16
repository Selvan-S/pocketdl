import type { AnalyzeResponse, CaptureDownloadRequest, CaptureItem, DownloadCreateRequest, DownloadItem, SettingsResponse, SystemStatus } from '../types/api';

const API_BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
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
};
