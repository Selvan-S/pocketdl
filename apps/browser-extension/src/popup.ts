import { DEFAULT_BACKEND_URL, getBackendUrl, normalizeBackendUrl } from './config.js';
import type { CaptureAttemptStatus, SendAttemptStatus } from './models.js';

let latestItems: CaptureItem[] = [];
let latestDownloads: DownloadSummary[] = [];
// The popup re-renders on a 5s poll, so a quality picked in the DOM would be
// lost on the next tick. Undefined (or absent) means "let the site decide".
const selectedVariants = new Map<string, number | undefined>();
// Re-rendering drops the <details> open state with the old DOM, so it has to
// be tracked here and restored.
const expandedCaptures = new Set<string>();

interface CaptureVariant {
  index: number;
  quality_label: string;
  bandwidth_bps: number | null;
  has_separate_audio: boolean;
  estimated_size_bytes: number | null;
}

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
  variants_status: 'pending' | 'ready' | 'failed' | 'none';
  variants: CaptureVariant[];
}

interface DownloadSummary {
  id: string;
  capture_id: string | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  speed_bytes: number | null;
  error: string | null;
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

function formatAge(createdAt: string): string {
  const then = new Date(createdAt).getTime();
  if (!Number.isFinite(then)) return '';
  const minutes = Math.floor((Date.now() - then) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function metadataText(item: CaptureItem): string {
  if (item.metadata_status === 'pending') return 'Analyzing…';
  const parts = [`Duration ${formatDuration(item.duration_seconds)}`, `Size ${formatBytes(item.size_bytes)}`];
  if (item.width && item.height) parts.push(`${item.width}×${item.height}`);
  return parts.join(' · ');
}

function qualityHtml(item: CaptureItem): string {
  if (item.variants.length === 0) return '';
  const selected = selectedVariants.get(item.id);
  const chip = (index: number | undefined, label: string, detail: string) => `
    <button class="quality ${selected === index ? 'selected' : ''}" data-action="quality"
      data-capture-id="${escapeHtml(item.id)}" ${index === undefined ? '' : `data-variant-index="${index}"`}>
      ${escapeHtml(label)}${detail ? `<small>${escapeHtml(detail)}</small>` : ''}
    </button>`;
  const options = item.variants.map((variant) => {
    // An HLS stream's exact size is unknowable before downloading, so this
    // stays explicitly an estimate.
    const detail = variant.estimated_size_bytes ? `~${formatBytes(variant.estimated_size_bytes)}` : '';
    return chip(variant.index, variant.quality_label, detail);
  });
  return `<div class="capture-quality">${chip(undefined, 'Site default', '')}${options.join('')}</div>`;
}

function downloadFor(captureId: string): DownloadSummary | undefined {
  // /api/downloads is already ordered newest-first, so the first match per
  // capture is the most recent attempt.
  return latestDownloads.find((download) => download.capture_id === captureId);
}

function primaryActionHtml(item: CaptureItem): string {
  const download = downloadFor(item.id);
  if (!download || download.status === 'failed' || download.status === 'cancelled') {
    const errorLine = download?.status === 'failed' && download.error
      ? `<div class="capture-error">${escapeHtml(download.error)}</div>`
      : '';
    return `
      <button class="download" data-action="download" data-capture-id="${escapeHtml(item.id)}">Download</button>
      ${errorLine}
    `;
  }
  if (download.status === 'queued' || download.status === 'running') {
    const speed = download.speed_bytes ? ` · ${escapeHtml(formatBytes(download.speed_bytes))}/s` : '';
    return `<div class="capture-progress">Downloading… ${Math.round(download.progress)}%${speed}</div>`;
  }
  return `
    <div class="capture-downloaded">
      <span>Downloaded ✓</span>
      <button class="secondary" data-action="open-folder">Open folder</button>
    </div>
  `;
}

function render(items: CaptureItem[]): void {
  latestItems = items;
  const root = document.querySelector<HTMLDivElement>('#captures');
  if (!root) return;
  root.innerHTML = items.slice(0, 8).map((item) => `
    <details class="capture" data-capture-id="${escapeHtml(item.id)}" ${expandedCaptures.has(item.id) ? 'open' : ''}>
      <summary>
        <span class="capture-title">${escapeHtml(item.page_title || item.capture_type.toUpperCase())}</span>
        <span class="capture-meta">${escapeHtml(metadataText(item))}</span>
        ${item.looks_suspicious ? '<span class="capture-warning">Possibly a fragment, not the full video</span>' : ''}
      </summary>
      <div class="capture-body">
        <span>${escapeHtml(item.page_url || 'Captured media')}</span>
        <small title="${escapeHtml(new Date(item.created_at).toLocaleString())}">${escapeHtml(formatAge(item.created_at))}</small>
        ${qualityHtml(item)}
        ${primaryActionHtml(item)}
        <div class="capture-actions">
          <button class="secondary" data-action="copy" data-capture-id="${escapeHtml(item.id)}" data-media-url="${escapeHtml(item.media_url)}">Copy</button>
          <button class="secondary" data-action="open" data-capture-id="${escapeHtml(item.id)}">Open</button>
          <button class="secondary" data-action="remove" data-capture-id="${escapeHtml(item.id)}">Remove</button>
        </div>
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
      body: JSON.stringify({ variant_index: selectedVariants.get(id) }),
    });
    if (button) button.textContent = 'Queued';
  } catch (error) {
    if (button) button.textContent = 'Failed';
    const status = document.querySelector<HTMLDivElement>('#status');
    if (status) status.textContent = error instanceof Error ? error.message : 'Download failed';
  }
}

async function removeCapture(id: string): Promise<void> {
  const button = document.querySelector<HTMLButtonElement>(`button[data-action="remove"][data-capture-id="${CSS.escape(id)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = 'Removing…';
  }
  try {
    await request(`/api/captures/${encodeURIComponent(id)}`, { method: 'DELETE' });
    render(latestItems.filter((item) => item.id !== id));
  } catch (error) {
    if (button) button.textContent = 'Failed';
    const status = document.querySelector<HTMLDivElement>('#status');
    if (status) status.textContent = error instanceof Error ? error.message : 'Remove failed';
  }
}

async function openCapture(id: string): Promise<void> {
  const backendUrl = await getBackendUrl();
  await chrome.tabs.create({ url: `${backendUrl}/?capture=${encodeURIComponent(id)}` });
}

async function copyCapture(id: string, mediaUrl: string): Promise<void> {
  const button = document.querySelector<HTMLButtonElement>(`button[data-action="copy"][data-capture-id="${CSS.escape(id)}"]`);
  try {
    await navigator.clipboard.writeText(mediaUrl);
    if (button) {
      const original = button.textContent;
      button.textContent = 'Copied';
      setTimeout(() => { if (button) button.textContent = original; }, 1500);
    }
  } catch (error) {
    if (button) button.textContent = 'Failed';
    const status = document.querySelector<HTMLDivElement>('#status');
    if (status) status.textContent = error instanceof Error ? error.message : 'Copy failed';
  }
}

async function openDownloadFolder(): Promise<void> {
  try {
    await request('/api/settings/open-download-directory', { method: 'POST' });
  } catch (error) {
    const status = document.querySelector<HTMLDivElement>('#status');
    if (status) status.textContent = error instanceof Error ? error.message : 'Unable to open download folder';
  }
}

function renderBanner(attempt: CaptureAttemptStatus | null): void {
  const banner = document.querySelector<HTMLDivElement>('#banner');
  if (!banner) return;
  if (!attempt || attempt.ok) {
    banner.classList.remove('visible');
    banner.innerHTML = '';
    return;
  }
  banner.classList.add('visible');
  banner.innerHTML = `
    <span>PocketDL was unreachable when a capture was attempted at ${escapeHtml(new Date(attempt.at).toLocaleTimeString())} — it may not have been recorded.</span>
    <button class="dismiss" data-action="dismiss-banner" type="button">Dismiss</button>
  `;
}

function renderSendBanner(attempt: SendAttemptStatus | null): void {
  const banner = document.querySelector<HTMLDivElement>('#send-banner');
  if (!banner) return;
  if (!attempt) {
    banner.classList.remove('visible', 'ok');
    banner.innerHTML = '';
    return;
  }
  banner.classList.add('visible');
  banner.classList.toggle('ok', attempt.ok);
  const when = escapeHtml(new Date(attempt.at).toLocaleTimeString());
  banner.innerHTML = attempt.ok
    ? `<span>Sent to PocketDL at ${when}.</span>
       <button class="dismiss" data-action="dismiss-send" type="button">Dismiss</button>`
    : `<span>Send to PocketDL failed at ${when}: ${escapeHtml(attempt.error ?? 'unknown error')}.</span>
       <button class="dismiss" data-action="dismiss-send" type="button">Dismiss</button>`;
}

async function refresh(): Promise<void> {
  const status = document.querySelector<HTMLDivElement>('#status');
  try {
    latestDownloads = await request<DownloadSummary[]>('/api/downloads');
  } catch {
    // Best-effort: progress/downloaded state just won't be current this cycle.
  }
  try {
    const items = await request<CaptureItem[]>('/api/captures');
    render(items);
    if (status) status.textContent = `Connected · ${items.length} unique capture(s)`;
  } catch (error) {
    if (status) status.textContent = `Offline · ${error instanceof Error ? error.message : 'cannot connect'}`;
  }
  const { lastCaptureAttempt, lastSendAttempt } = await chrome.storage.local.get<{
    lastCaptureAttempt: CaptureAttemptStatus | null;
    lastSendAttempt: SendAttemptStatus | null;
  }>({ lastCaptureAttempt: null, lastSendAttempt: null });
  renderBanner(lastCaptureAttempt);
  renderSendBanner(lastSendAttempt);
}

document.querySelector<HTMLFormElement>('#settings')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = document.querySelector<HTMLInputElement>('#backend-url');
  if (!input) return;
  const backendUrl = normalizeBackendUrl(input.value || DEFAULT_BACKEND_URL);
  await chrome.storage.local.set({ backendUrl });
  await refresh();
});

// `toggle` does not bubble, so it is observed in the capture phase.
document.querySelector<HTMLDivElement>('#captures')?.addEventListener('toggle', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLDetailsElement)) return;
  const id = target.dataset.captureId;
  if (!id) return;
  if (target.open) expandedCaptures.add(id);
  else expandedCaptures.delete(id);
}, true);

document.querySelector<HTMLDivElement>('#captures')?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const action = target.dataset.action;
  if (action === 'open-folder') {
    void openDownloadFolder();
    return;
  }
  const id = target.dataset.captureId;
  if (!id) return;
  if (action === 'quality') {
    const raw = target.dataset.variantIndex;
    selectedVariants.set(id, raw === undefined ? undefined : Number(raw));
    render(latestItems);
    return;
  }
  if (action === 'download') void downloadCapture(id);
  else if (action === 'open') void openCapture(id);
  else if (action === 'remove') void removeCapture(id);
  else if (action === 'copy') void copyCapture(id, target.dataset.mediaUrl ?? '');
});

document.querySelector<HTMLDivElement>('#banner')?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement) || target.dataset.action !== 'dismiss-banner') return;
  void chrome.storage.local.set({ lastCaptureAttempt: null }).then(() => renderBanner(null));
});

document.querySelector<HTMLDivElement>('#send-banner')?.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement) || target.dataset.action !== 'dismiss-send') return;
  void chrome.storage.local.set({ lastSendAttempt: null }).then(() => renderSendBanner(null));
});

const versionLabel = document.querySelector<HTMLSpanElement>('#version');
if (versionLabel) versionLabel.textContent = `v${chrome.runtime.getManifest().version}`;

void getBackendUrl().then((url) => {
  const input = document.querySelector<HTMLInputElement>('#backend-url');
  if (input) input.value = url;
});

void refresh();
setInterval(() => void refresh(), 5000);
