import { useState } from 'react';
import type { CaptureDownloadRequest, CaptureItem } from '../types/api';

interface Props {
  items: CaptureItem[];
  onDownload: (id: string, payload: CaptureDownloadRequest) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
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

function CaptureCard({ item, onDownload, onDelete }: Props & { item: CaptureItem }) {
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

  return (
    <article className="capture-card">
      <div className="capture-card-header">
        <div className="capture-card-title">
          <div className="eyebrow">CAPTURED {item.capture_type.toUpperCase()}</div>
          <h3>{item.page_title || 'Untitled browser media'}</h3>
          <p>{item.page_url || 'Direct media request'}</p>
        </div>
        <span className={`status-badge ${item.status}`}>{item.status}</span>
      </div>
      <div className="capture-source-row">
        <span className="capture-source-kind">{item.capture_type.toUpperCase()}</span>
        {item.content_type && <span>{item.content_type}</span>}
      </div>
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
      <div className="capture-actions">
        <button className="primary" disabled={busy} onClick={download}>{busy ? 'Queuing…' : 'Download'}</button>
        <button className="secondary" disabled={busy} onClick={() => void onDelete(item.id)}>Remove</button>
      </div>
    </article>
  );
}
