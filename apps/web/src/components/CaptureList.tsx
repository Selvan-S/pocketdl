import { useState } from 'react';
import type { CaptureDownloadRequest, CaptureItem } from '../types/api';

interface CaptureActions {
  onDownload: (id: string, payload: CaptureDownloadRequest) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

interface Props extends CaptureActions {
  items: CaptureItem[];
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
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}` : `${minutes}:${String(secs).padStart(2, '0')}`;
}

function metadataLabel(item: CaptureItem): string {
  if (item.metadata_status === 'pending') return 'Analyzing media…';
  const values = [`Duration ${formatDuration(item.duration_seconds)}`, `Size ${formatBytes(item.size_bytes)}`];
  if (item.width && item.height) values.push(`${item.width}×${item.height}`);
  return values.join(' · ');
}

export function CaptureList({ items, onDownload, onDelete }: Props) {
  return (
    <section className="capture-list">
      {items.length === 0 ? (
        <div className="empty-state">
          <strong>No browser captures yet.</strong>
          <span>Play a video in Chrome with PocketDL Capture enabled.</span>
        </div>
      ) : items.map((item) => <CaptureCard key={item.id} item={item} onDownload={onDownload} onDelete={onDelete} />)}
    </section>
  );
}

function CaptureCard({ item, onDownload, onDelete }: CaptureActions & { item: CaptureItem }) {
  const [filename, setFilename] = useState(item.page_title ?? '');
  const [preset, setPreset] = useState<CaptureDownloadRequest['preset']>('best');
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      await onDownload(item.id, { filename: filename.trim() || undefined, preset });
    } finally {
      setBusy(false);
    }
  };

  const suspicious = item.capture_type === 'media' && item.duration_seconds != null && item.duration_seconds < 10;

  return (
    <details className="capture-card">
      <summary className="capture-summary">
        <div className="capture-card-header">
          <div className="capture-card-title">
            <div className="eyebrow">CAPTURED {item.capture_type.toUpperCase()}</div>
            <h3>{item.page_title || 'Untitled browser media'}</h3>
            <p>{item.page_url || 'Direct media request'}</p>
          </div>
          <div className="capture-summary-side">
            <span className={`status-badge ${item.status}`}>{item.status}</span>
            <span className="capture-chevron">＋</span>
          </div>
        </div>
        <div className="capture-source-row">
          <span className="capture-source-kind">{item.capture_type.toUpperCase()}</span>
          {item.content_type && <span>{item.content_type}</span>}
          <span>{metadataLabel(item)}</span>
          {suspicious && <span className="capture-warning">Very short media</span>}
        </div>
      </summary>

      <div className="capture-expanded">
        <details className="capture-details">
          <summary>Show captured source</summary>
          <code>{item.media_url}</code>
        </details>

        <div className="capture-fields">
          <label>
            Filename
            <input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="Use page title" />
          </label>
          <label>
            Quality
            <select value={preset} onChange={(e) => setPreset(e.target.value as CaptureDownloadRequest['preset'])}>
              <option value="best">Best</option>
              <option value="1080p">Up to 1080p</option>
              <option value="720p">Up to 720p</option>
              <option value="audio">Audio only</option>
            </select>
          </label>
        </div>

        {item.metadata_status === 'failed' && item.metadata_error && (
          <div className="capture-metadata-warning">Metadata unavailable: {item.metadata_error}</div>
        )}

        <div className="capture-actions">
          <button className="primary" disabled={busy} onClick={download}>{busy ? 'Queuing…' : 'Download'}</button>
          <button className="secondary" disabled={busy} onClick={() => void onDelete(item.id)}>Remove</button>
        </div>
      </div>
    </details>
  );
}
