import type { DownloadItem } from '../types/api';

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

export function DownloadList({ items, onCancel, onDelete }: {
  items: DownloadItem[];
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (items.length === 0) return <div className="empty">No downloads yet.</div>;

  return (
    <div className="downloads">
      {items.map((item) => (
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
            <div className="error">
              {item.error_category && <strong>{item.error_category.replaceAll('_', ' ').toUpperCase()}: </strong>}
              {item.error}
            </div>
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
            {(item.status === 'failed' || item.status === 'completed' || item.status === 'cancelled') && <button onClick={() => onDelete(item.id)}>Remove</button>}
          </div>
        </article>
      ))}
    </div>
  );
}
