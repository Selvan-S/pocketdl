import { useState } from 'react';
import type { CaptureDownloadRequest, CaptureItem, CaptureVariant } from '../types/api';

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

function variantDetail(variant: CaptureVariant): string {
  const parts: string[] = [];
  if (variant.bandwidth_bps) parts.push(`${(variant.bandwidth_bps / 1_000_000).toFixed(1)} Mbps`);
  if (variant.frame_rate) parts.push(`${Math.round(variant.frame_rate)} fps`);
  // Never rendered as a plain size: an HLS stream's byte count cannot be known
  // before downloading it, and a wrong exact number is worse than an honest
  // approximate one.
  if (variant.estimated_size_bytes) parts.push(`~${formatBytes(variant.estimated_size_bytes)} est.`);
  return parts.join(' · ');
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
  // undefined means "let the site decide" -- ffmpeg reads the master and picks
  // its default rather than us forcing a quality the user did not choose.
  const [variantIndex, setVariantIndex] = useState<number | undefined>(undefined);
  const [subtitles, setSubtitles] = useState(false);
  const [busy, setBusy] = useState(false);

  const hasVariants = item.variants.length > 0;
  const selected = item.variants.find((variant) => variant.index === variantIndex);

  const download = async () => {
    setBusy(true);
    try {
      await onDownload(item.id, {
        filename: filename.trim() || undefined,
        variant_index: variantIndex,
        subtitles: subtitles || undefined,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <details id={`capture-${item.id}`} className="capture-card">
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
          {hasVariants && <span className="capture-quality-count">{item.variants.length} qualities</span>}
          {item.looks_suspicious && <span className="capture-warning">Possibly a fragment, not the full video</span>}
        </div>
      </summary>

      <div className="capture-expanded">
        <details className="capture-details">
          <summary>Show captured source</summary>
          <code>{selected ? selected.url : item.media_url}</code>
        </details>

        <div className="capture-fields">
          <label>
            Filename
            <input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="Use page title" />
          </label>
        </div>

        <div className="capture-quality">
          <span className="capture-quality-title">Quality</span>
          {hasVariants ? (
            <>
              <div className="capture-quality-options">
                <button
                  type="button"
                  className={`quality-chip ${variantIndex === undefined ? 'selected' : ''}`}
                  onClick={() => setVariantIndex(undefined)}
                >
                  Site default
                </button>
                {item.variants.map((variant) => (
                  <button
                    key={variant.index}
                    type="button"
                    className={`quality-chip ${variantIndex === variant.index ? 'selected' : ''}`}
                    onClick={() => setVariantIndex(variant.index)}
                    title={variant.codecs ?? undefined}
                  >
                    <strong>{variant.quality_label}</strong>
                    {variantDetail(variant) && <span>{variantDetail(variant)}</span>}
                  </button>
                ))}
              </div>
              {selected?.has_separate_audio && (
                <div className="capture-quality-note">Audio is a separate track and will be merged in.</div>
              )}
            </>
          ) : (
            <div className="capture-quality-note">
              {item.variants_status === 'pending'
                ? 'Checking which qualities this source offers…'
                : item.variants_status === 'failed'
                  ? 'Could not read the playlist, so the site default quality will be downloaded.'
                  : 'This source offers a single quality.'}
            </div>
          )}
        </div>

        {item.metadata_status === 'failed' && item.metadata_error && (
          <div className="capture-metadata-warning">Metadata unavailable: {item.metadata_error}</div>
        )}

        {item.capture_type === 'hls' && (
          <label className="checkbox-chip capture-subtitle-toggle">
            <input type="checkbox" checked={subtitles} onChange={(event) => setSubtitles(event.target.checked)} />
            Include subtitles (if the stream has any)
          </label>
        )}

        <div className="capture-actions">
          <button className="primary" disabled={busy} onClick={download}>{busy ? 'Queuing…' : 'Download'}</button>
          <button className="secondary" disabled={busy} onClick={() => void onDelete(item.id)}>Remove</button>
        </div>
      </div>
    </details>
  );
}
