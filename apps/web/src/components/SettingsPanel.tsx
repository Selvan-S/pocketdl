import { useEffect, useState } from 'react';
import type { SettingsResponse } from '../types/api';

interface Props {
  value: SettingsResponse | null;
  onSave: (path: string) => Promise<SettingsResponse>;
  onReset: () => Promise<SettingsResponse>;
  onOpen: () => Promise<void>;
  busy: boolean;
}

export function SettingsPanel({ value, onSave, onReset, onOpen, busy }: Props) {
  const [path, setPath] = useState('');

  useEffect(() => {
    setPath(value?.download_directory ?? '');
  }, [value?.download_directory]);

  async function save() {
    const next = path.trim();
    if (!next) return;
    await onSave(next);
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
        <button disabled={busy || !path.trim()} onClick={() => void save()}>{busy ? 'Saving…' : 'Save location'}</button>
        <button className="secondary" disabled={busy} onClick={() => void onOpen()}>Open folder</button>
        <button className="secondary" disabled={busy} onClick={() => void onReset()}>Reset default</button>
      </div>
      {value && <div className="settings-default">Default: {value.default_download_directory}</div>}
    </section>
  );
}
