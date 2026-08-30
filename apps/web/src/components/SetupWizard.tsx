import { useEffect, useState } from 'react';
import type { SettingsResponse } from '../types/api';

interface Props {
  settings: SettingsResponse | null;
  onSaveLocation: (path: string) => Promise<SettingsResponse>;
  onFinish: () => void;
}

// A one-time guided setup for a self-hosted tool where there's no one else to
// ask "why isn't this working". Shown until the user completes or skips it
// (tracked in localStorage by App). Three short steps: choose where downloads
// go, install the capture extension, done.
export function SetupWizard({ settings, onSaveLocation, onFinish }: Props) {
  const [step, setStep] = useState(0);
  const [path, setPath] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (settings?.download_directory) setPath(settings.download_directory);
  }, [settings?.download_directory]);

  async function saveLocation() {
    const next = path.trim();
    if (!next) {
      setStep(1);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSaveLocation(next);
      setStep(1);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Could not save that location.');
    } finally {
      setSaving(false);
    }
  }

  const steps = [
    {
      title: 'Where should downloads go?',
      body: (
        <>
          <p>Pick the folder PocketDL saves media into. You can change it any time in Settings.</p>
          <label htmlFor="wizard-path">Download directory</label>
          <input
            id="wizard-path"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="C:\\Users\\You\\Downloads\\PocketDL"
            autoComplete="off"
          />
          <div className="field-help">
            Use an absolute path. On Termux/Android, something like <code>/sdcard/Download/PocketDL</code> works.
          </div>
          {error && <div className="error">{error}</div>}
        </>
      ),
      actions: (
        <>
          <button className="link-button" onClick={onFinish}>Skip setup</button>
          <button disabled={saving} onClick={() => void saveLocation()}>{saving ? 'Saving…' : 'Save & continue'}</button>
        </>
      ),
    },
    {
      title: 'Install the capture extension (optional)',
      body: (
        <>
          <p>
            For HLS/DASH sites where a plain URL won’t work, the browser extension captures the media stream and
            sends it here. It’s optional — normal downloads work without it.
          </p>
          <ol className="wizard-steps">
            <li>Open your Chromium browser’s Extensions page (<code>chrome://extensions</code>).</li>
            <li>Turn on <strong>Developer mode</strong>.</li>
            <li>Choose <strong>Load unpacked</strong> and select the <code>apps/browser-extension</code> folder.</li>
            <li>Open the extension’s popup and confirm the backend URL matches this app.</li>
          </ol>
          <div className="field-help">You can do this later; the “Send to PocketDL” right-click action lives here too.</div>
        </>
      ),
      actions: (
        <>
          <button className="secondary" onClick={() => setStep(0)}>Back</button>
          <button onClick={() => setStep(2)}>Continue</button>
        </>
      ),
    },
    {
      title: 'You’re set up',
      body: (
        <>
          <p>Paste a URL to download, or capture a stream with the extension. Playlists, presets, subtitles and more are in the panels below.</p>
          <div className="field-help">Saving to: {settings?.download_directory ?? (path || 'the default folder')}</div>
        </>
      ),
      actions: (
        <>
          <button className="secondary" onClick={() => setStep(1)}>Back</button>
          <button onClick={onFinish}>Finish</button>
        </>
      ),
    },
  ];

  const current = steps[step];

  return (
    <div className="wizard-overlay" role="dialog" aria-modal="true" aria-label="PocketDL setup">
      <div className="wizard-card">
        <div className="wizard-progress">Step {step + 1} of {steps.length}</div>
        <h2>{current.title}</h2>
        <div className="wizard-body">{current.body}</div>
        <div className="wizard-actions">{current.actions}</div>
      </div>
    </div>
  );
}
