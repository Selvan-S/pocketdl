import { useCallback, useState } from 'react';
import { api } from '../api/client';
import type { StorageUsage } from '../types/api';

function formatBytes(value: number): string {
  if (value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function StoragePanel() {
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUsage(await api.storage());
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to read storage usage.');
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <details
      className="section-collapsible"
      onToggle={(event) => {
        // Scanning a large tree is slow, so only scan when the section is
        // actually opened, and only the first time.
        if ((event.target as HTMLDetailsElement).open && usage === null && !loading) void load();
      }}
    >
      <summary className="section-collapsible-summary">
        <div>
          <div className="eyebrow">STORAGE</div>
          <h2>Disk usage</h2>
          <span>
            {usage
              ? `${formatBytes(usage.total_bytes)} in ${usage.folders.length} folder(s) · ${formatBytes(usage.free_bytes)} free`
              : 'Expand to scan the download folder'}
          </span>
        </div>
        <span className="section-chevron">−</span>
      </summary>
      <div className="storage-panel">
        <div className="section-toolbar-actions">
          <button className="secondary compact" disabled={loading} onClick={() => void load()}>
            {loading ? 'Scanning…' : 'Rescan'}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
        {usage && (
          <>
            <div className="storage-summary">
              <span>Used here: <strong>{formatBytes(usage.total_bytes)}</strong></span>
              <span>Free on disk: <strong>{formatBytes(usage.free_bytes)}</strong></span>
              <span>Disk size: <strong>{formatBytes(usage.disk_total_bytes)}</strong></span>
            </div>
            {usage.folders.length === 0 ? (
              <div className="empty">Nothing downloaded yet.</div>
            ) : (
              <ul className="storage-folders">
                {usage.folders.map((folder) => {
                  const pct = usage.total_bytes ? Math.round((folder.bytes / usage.total_bytes) * 100) : 0;
                  return (
                    <li key={folder.name}>
                      <div className="storage-folder-head">
                        <span className="filename">{folder.name}</span>
                        <span>{formatBytes(folder.bytes)} · {folder.file_count} file(s)</span>
                      </div>
                      <div className="progress-track"><div className="progress" style={{ width: `${pct}%` }} /></div>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </details>
  );
}
