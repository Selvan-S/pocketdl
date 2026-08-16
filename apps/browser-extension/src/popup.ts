import { DEFAULT_BACKEND_URL, getBackendUrl, normalizeBackendUrl } from './config.js';

interface CaptureItem {
  id: string;
  media_url: string;
  page_url: string | null;
  page_title: string | null;
  capture_type: string;
  status: string;
  created_at: string;
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

function render(items: CaptureItem[]): void {
  const root = document.querySelector<HTMLDivElement>('#captures');
  if (!root) return;
  root.innerHTML = items.slice(0, 8).map((item) => `
    <article class="capture" data-capture-id="${escapeHtml(item.id)}">
      <strong>${escapeHtml(item.page_title || item.capture_type.toUpperCase())}</strong>
      <span>${escapeHtml(item.page_url || 'Captured media')}</span>
      <small>${new Date(item.created_at).toLocaleTimeString()}</small>
      <button class="download" data-action="download" data-capture-id="${escapeHtml(item.id)}">Download</button>
    </article>
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
    if (status) status.textContent = `Connected · ${items.length} capture(s)`;
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
