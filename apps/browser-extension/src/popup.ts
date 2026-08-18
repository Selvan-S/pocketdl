import { DEFAULT_BACKEND_URL, getBackendUrl, normalizeBackendUrl } from './config.js';

interface CaptureItem {
  id: string;
  media_url: string;
  page_url: string | null;
  page_title: string | null;
  capture_type: string;
  status: string;
  created_at: string;
  size_bytes: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  metadata_status: 'pending' | 'ready' | 'failed';
  looks_suspicious: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const backendUrl = await getBackendUrl();
  const response = await fetch(`${backendUrl}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char] ?? char);
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  for (const unit of units) {
    if (value < 1024 || unit === 'TB') return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${unit}`;
    value /= 1024;
  }
  return `${bytes} B`;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function metadataText(item: CaptureItem): string {
  if (item.metadata_status === 'pending') return 'Analyzing…';
  const parts = [`Duration ${formatDuration(item.duration_seconds)}`, `Size ${formatBytes(item.size_bytes)}`];
  if (item.width && item.height) parts.push(`${item.width}×${item.height}`);
  return parts.join(' · ');
}

function render(items: CaptureItem[]): void {
  const root = document.querySelector<HTMLDivElement>('#captures');
  if (!root) return;
  root.innerHTML = items.slice(0, 8).map((item) => `
    <details class="capture">
      <summary>
        <span class="capture-title">${escapeHtml(item.page_title || item.capture_type.toUpperCase())}</span>
        <span class="capture-meta">${escapeHtml(metadataText(item))}</span>
        ${item.looks_suspicious ? '<span class="capture-warning">Possibly a fragment, not the full video</span>' : ''}
      </summary>
      <div class="capture-body">
        <span>${escapeHtml(item.page_url || 'Captured media')}</span>
        <small>${new Date(item.created_at).toLocaleTimeString()}</small>
        <button class="download" data-action="download" data-capture-id="${escapeHtml(item.id)}">Download</button>
      </div>
    </details>
  `).join('') || '<p class="muted">No captured streams yet.</p>';
}

async function downloadCapture(id: string): Promise<void> {
  const button = document.querySelector<HTMLButtonElement>(`button[data-action="download"][data-capture-id="${CSS.escape(id)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = 'Queuing…';
  }
  try {
    await request(`/api/captures/${encodeURIComponent(id)}/download`, {
      method: 'POST',
      body: JSON.stringify({ preset: 'best' }),
    });
    if (button) button.textContent = 'Queued';
  } catch (error) {
    if (button) button.textContent = 'Failed';
    const status = document.querySelector<HTMLDivElement>('#status');
    if (status) status.textContent = error instanceof Error ? error.message : 'Download failed';
  }
}

async function refresh(): Promise<void> {
  const status = document.querySelector<HTMLDivElement>('#status');
  try {
    const items = await request<CaptureItem[]>('/api/captures');
    render(items);
    if (status) status.textContent = `Connected · ${items.length} unique capture(s)`;
  } catch (error) {
    if (status) status.textContent = `Offline · ${error instanceof Error ? error.message : 'cannot connect'}`;
  }
}

document.querySelector<HTMLFormElement>('#settings')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = document.querySelector<HTMLInputElement>('#backend-url');
  if (!input) return;
  const backendUrl = normalizeBackendUrl(input.value || DEFAULT_BACKEND_URL);
  await chrome.storage.local.set({ backendUrl });
  await refresh();
});

document.querySelector<HTMLDivElement>('#captures')?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  if (target.dataset.action !== 'download') return;
  const id = target.dataset.captureId;
  if (id) void downloadCapture(id);
});

void getBackendUrl().then((url) => {
  const input = document.querySelector<HTMLInputElement>('#backend-url');
  if (input) input.value = url;
});

void refresh();
setInterval(() => void refresh(), 5000);
