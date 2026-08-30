import { useEffect, useMemo, useState } from 'react';
import type { DownloadErrorCategory, DownloadItem, DownloadStatus } from '../types/api';

// Turns an opaque error category into an actionable hint. Rate limiting is
// the one that most needs it: the fix is to *wait*, and retrying eagerly can
// make it worse (an account can get temporarily restricted). Returns null
// when the raw error line already speaks for itself.
function guidanceFor(category: DownloadErrorCategory | null): string | null {
  switch (category) {
    case 'rate_limited':
      return 'The site is rate-limiting requests. Wait a few minutes before retrying — repeated attempts can extend the block.';
    case 'authentication_required':
      return 'This needs a signed-in session. Add the site’s session/cookie, then retry.';
    case 'http_403':
      return 'The server refused the request (403). For HLS/DASH sites, try Browser Capture instead.';
    case 'geo_restriction':
      return 'This media isn’t available in your region.';
    case 'drm':
      return 'This media is DRM-protected and cannot be downloaded.';
    case 'network_error':
      return 'Network problem reaching the site. Check your connection, then retry.';
    default:
      return null;
  }
}

// The downloads list grows without bound as history accumulates. Tabs split
// it by state and pagination bounds what is rendered, the same shape as the
// playlist fix -- see Round 10 in docs/docs_POCKETDL_ROADMAP.md. This is
// client-side: the full list already arrives on the SSE snapshot, so no extra
// request is made; note the snapshot payload itself still carries every job.
const DOWNLOADS_PAGE_SIZE = 20;

const ACTIVE_STATUSES: DownloadStatus[] = ['queued', 'running'];

type DownloadTab = 'active' | 'completed' | 'all';

const DOWNLOAD_TABS: Array<{ value: DownloadTab; label: string }> = [
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
  { value: 'all', label: 'All' },
];

function inTab(item: DownloadItem, tab: DownloadTab): boolean {
  if (tab === 'all') return true;
  const active = ACTIVE_STATUSES.includes(item.status);
  return tab === 'active' ? active : !active;
}

function formatBytes(value: number | null): string {
  if (value == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatSpeed(value: number | null): string {
  return value == null ? '—' : `${formatBytes(value)}/s`;
}

export function DownloadList({ items, onCancel, onRetry, onDelete }: {
  items: DownloadItem[];
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [tab, setTab] = useState<DownloadTab>('all');
  const [page, setPage] = useState(0);

  const counts = useMemo(() => ({
    active: items.filter((item) => inTab(item, 'active')).length,
    completed: items.filter((item) => inTab(item, 'completed')).length,
    all: items.length,
  }), [items]);

  const filtered = useMemo(() => items.filter((item) => inTab(item, tab)), [items, tab]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / DOWNLOADS_PAGE_SIZE));

  // The list updates live off the SSE stream, so a page can empty out (jobs
  // finishing, being removed) under the current page -- clamp back into range.
  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  const visible = filtered.slice(page * DOWNLOADS_PAGE_SIZE, page * DOWNLOADS_PAGE_SIZE + DOWNLOADS_PAGE_SIZE);

  if (items.length === 0) return <div className="empty">No downloads yet.</div>;

  return (
    <div className="downloads">
      <div className="playlist-tabs">
        {DOWNLOAD_TABS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            className={`playlist-tab ${tab === value ? 'active' : ''}`}
            onClick={() => { setTab(value); setPage(0); }}
          >
            {label} {counts[value]}
          </button>
        ))}
      </div>
      {visible.map((item) => (
        <article key={item.id} className="download-card">
          <div className="download-header">
            <div className="download-title-group">
              <strong>{item.title || item.filename || item.url}</strong>
              {item.filename && <span className="filename">Saved as: {item.filename}</span>}
            </div>
            <span className={`status ${item.status}`}>{item.status}</span>
          </div>
          <div className="progress-track"><div className="progress" style={{ width: `${Math.max(0, Math.min(100, item.progress))}%` }} /></div>
          <div className="download-meta">
            <span>{item.progress.toFixed(0)}%</span>
            <span>{formatSpeed(item.speed_bytes)}</span>
            <span>{formatBytes(item.downloaded_bytes)}{item.total_bytes ? ` / ${formatBytes(item.total_bytes)}` : ''}</span>
            {item.exit_code != null && <span>Exit code: {item.exit_code}</span>}
          </div>
          {item.error && (
            <div className={`error ${item.error_category === 'rate_limited' ? 'rate-limited' : ''}`}>
              {item.error_category && <strong>{item.error_category.replaceAll('_', ' ').toUpperCase()}: </strong>}
              {item.error}
            </div>
          )}
          {item.status === 'failed' && guidanceFor(item.error_category) && (
            <div className="field-help">{guidanceFor(item.error_category)}</div>
          )}
          {item.retry_count > 0 && <div className="field-help">Automatic retries: {item.retry_count} · Strategy: {item.impersonation}</div>}
          {item.status === 'failed' && item.error_details && (
            <details className="error-details">
              <summary>Show full yt-dlp output</summary>
              <pre>{item.error_details}</pre>
            </details>
          )}
          <div className="actions">
            {(item.status === 'queued' || item.status === 'running') && <button onClick={() => onCancel(item.id)}>Cancel</button>}
            {(item.status === 'failed' || item.status === 'cancelled') && <button onClick={() => onRetry(item.id)}>Retry</button>}
            {(item.status === 'failed' || item.status === 'completed' || item.status === 'cancelled') && <button onClick={() => onDelete(item.id)}>Remove</button>}
          </div>
        </article>
      ))}
      {filtered.length === 0 ? (
        <div className="empty">No {tab === 'all' ? '' : `${tab} `}downloads.</div>
      ) : pageCount > 1 ? (
        <div className="playlist-pager">
          <button type="button" className="secondary compact" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>
            Previous
          </button>
          <span>Page {page + 1} of {pageCount}</span>
          <button type="button" className="secondary compact" disabled={page >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
