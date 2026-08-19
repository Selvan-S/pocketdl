import type { AnalyzeResponse } from '../types/api';

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—';
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function formatBytes(value: number | null): string {
  if (value == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function describeFormat(item: AnalyzeResponse['formats'][number]): string {
  const fps = item.height && item.fps ? Math.round(item.fps) : null;
  const resolution = item.height ? `${item.height}p${fps ?? ''}` : item.width ? `${item.width}px` : 'audio';
  const codecs = [item.vcodec, item.acodec].filter(Boolean).join(' + ') || 'unknown codec';
  const ext = item.ext ? `.${item.ext}` : '';
  return `${resolution} · ${ext || 'format'} · ${codecs}`;
}

function describeRate(item: AnalyzeResponse['formats'][number]): string | null {
  return item.tbr ? `${Math.round(item.tbr)} kbps` : null;
}

interface Props {
  result: AnalyzeResponse;
  selectedFormatId: string | null;
  onSelectFormat: (formatId: string | null) => void;
}

export function AnalyzeResult({ result, selectedFormatId, onSelectFormat }: Props) {
  return (
    <section className="analysis-result" aria-live="polite">
      <div className="analysis-header">
        <div>
          <div className="eyebrow">ANALYSIS</div>
          <h3>{result.title || 'Untitled media'}</h3>
        </div>
        {result.is_live && <span className="live-badge">LIVE</span>}
      </div>

      <div className="analysis-meta">
        <span>Duration: {formatDuration(result.duration_seconds)}</span>
        {result.uploader && <span>Uploader: {result.uploader}</span>}
        {result.extractor && <span>Extractor: {result.extractor}</span>}
        <span>Formats: {result.formats.length}</span>
      </div>

      <div className="formats-grid">
        {result.formats.slice(0, 12).map((item) => {
          // Audio-only formats aren't individually selectable here: picking one
          // would need to skip the "+bestaudio" merge the backend always adds
          // for a selected format_id. Use the "Audio only" preset instead.
          const selectable = item.height != null;
          const selected = selectable && item.format_id === selectedFormatId;
          return (
            <button
              key={`${item.format_id}-${item.ext}-${item.height ?? 'audio'}`}
              type="button"
              className={`format-chip${selected ? ' format-chip-selected' : ''}`}
              disabled={!selectable}
              aria-pressed={selected}
              onClick={() => onSelectFormat(selected ? null : item.format_id)}
            >
              <strong>{describeFormat(item)}</strong>
              <span>{formatBytes(item.filesize)}{describeRate(item) ? ` · ${describeRate(item)}` : ''}{item.protocol ? ` · ${item.protocol}` : ''}</span>
            </button>
          );
        })}
      </div>

      {selectedFormatId && (
        <div className="field-help">
          Downloading exactly this format instead of the quality preset below.{' '}
          <button type="button" className="link-button" onClick={() => onSelectFormat(null)}>Use quality preset instead</button>
        </div>
      )}

      {result.formats.length > 12 && <div className="field-help">Showing the first 12 formats.</div>}
    </section>
  );
}
