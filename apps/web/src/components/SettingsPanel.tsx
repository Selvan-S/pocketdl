import { useEffect, useState, type ChangeEvent } from 'react';
import type { SettingsResponse } from '../types/api';

interface Props {
  value: SettingsResponse | null;
  onSave: (path: string) => Promise<SettingsResponse>;
  onReset: () => Promise<SettingsResponse>;
  onOpen: () => Promise<void>;
  onBrowse: () => Promise<string | null>;
  onExport: () => Promise<void>;
  onImport: (file: File) => Promise<void>;
  busy: boolean;
}

export function SettingsPanel({ value, onSave, onReset, onOpen, onBrowse, onExport, onImport, busy }: Props) {
  const [path, setPath] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const [transferring, setTransferring] = useState(false);

  useEffect(() => {
    setPath(value?.download_directory ?? '');
  }, [value?.download_directory]);

  async function save() {
    const next = path.trim();
    if (!next) return;
    await onSave(next);
  }

  async function browse() {
    setBrowsing(true);
    try {
      const chosen = await onBrowse();
      if (chosen) setPath(chosen);
    } finally {
      setBrowsing(false);
    }
  }

  async function exportBackup() {
    setTransferring(true);
    try {
      await onExport();
    } finally {
      setTransferring(false);
    }
  }

  async function importBackup(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset immediately so re-selecting the same file fires change again.
    event.target.value = '';
    if (!file) return;
    setTransferring(true);
    try {
      await onImport(file);
    } finally {
      setTransferring(false);
    }
  }

  return (
    <section className="settings-panel panel">
      <div className="settings-header">
        <div>
          <div className="eyebrow">SETTINGS</div>
          <h2>Download location</h2>
          <p>New downloads will use this folder. Existing running downloads keep their current destination.</p>
        </div>
      </div>
      <label htmlFor="download-directory">Download directory</label>
      <input
        id="download-directory"
        value={path}
        onChange={(event) => setPath(event.target.value)}
        placeholder="C:\\Users\\You\\Downloads\\PocketDL"
        autoComplete="off"
      />
      <div className="field-help">
        Use an absolute path. On Termux, a path such as <code>/sdcard/Download/PocketDL</code> is valid.
      </div>
      <div className="settings-actions">
        <button className="secondary" disabled={busy || browsing} onClick={() => void browse()}>{browsing ? 'Opening…' : 'Browse…'}</button>
        <button disabled={busy || !path.trim()} onClick={() => void save()}>{busy ? 'Saving…' : 'Save location'}</button>
        <button className="secondary" disabled={busy} onClick={() => void onOpen()}>Open folder</button>
        <button className="secondary" disabled={busy} onClick={() => void onReset()}>Reset default</button>
      </div>
      {value && <div className="settings-default">Default: {value.default_download_directory}</div>}

      <div className="settings-header settings-subsection">
        <div>
          <h2>Backup &amp; restore</h2>
          <p>Export your settings, saved presets, and playlists to a JSON file, or import one. Import is additive — it never overwrites or deletes what you already have.</p>
        </div>
      </div>
      <div className="settings-actions">
        <button className="secondary" disabled={transferring} onClick={() => void exportBackup()}>
          {transferring ? 'Working…' : 'Export backup'}
        </button>
        <label className="secondary file-button">
          Import backup…
          <input type="file" accept="application/json,.json" disabled={transferring} onChange={(event) => void importBackup(event)} />
        </label>
      </div>
    </section>
  );
}
