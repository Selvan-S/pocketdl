import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api/client';
import { DownloadForm } from './components/DownloadForm';
import { DownloadList } from './components/DownloadList';
import { CaptureList } from './components/CaptureList';
import { InstagramPanel } from './components/InstagramPanel';
import { SettingsPanel } from './components/SettingsPanel';
import type { AnalyzeResponse, CaptureDownloadRequest, CaptureItem, DownloadCreateRequest, DownloadItem, SettingsResponse, SystemStatus } from './types/api';
import './styles.css';

export default function App() {
  const [downloads, setDownloads] = useState<DownloadItem[]>([]);
  const [captures, setCaptures] = useState<CaptureItem[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  // Tracks whether the *current* poll actually reached the backend, separate
  // from `status` (which deliberately keeps its last-known-good value across
  // a blip so displayed data doesn't flicker to empty). Without this, once
  // connected the pill would keep claiming "Backend connected" forever even
  // after the backend went unreachable, since `status` is only ever set on
  // success and nothing ever cleared it.
  const [connected, setConnected] = useState(false);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [message, setMessage] = useState('');
  const [updating, setUpdating] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);

  // The 2s poll and user actions (delete, cancel, ...) both call refresh(),
  // so calls can be in flight concurrently. Without this guard, a poll that
  // started before a delete can resolve after it with stale data and
  // resurrect the just-removed item until the next poll tick. Only the
  // most-recently-started call is allowed to apply its result.
  const refreshSeq = useRef(0);
  const refresh = useCallback(async () => {
    const seq = ++refreshSeq.current;
    // Each call is independent: one endpoint failing (e.g. /api/system/status
    // shelling out to check yt-dlp/ffmpeg) must not stop the others from
    // updating or leave the connection pill stuck on "Connecting…" forever.
    const [items, system, captured, nextSettings] = await Promise.allSettled([
      api.listDownloads(),
      api.status(),
      api.listCaptures(),
      api.settings(),
    ]);
    if (seq !== refreshSeq.current) return;
    if (items.status === 'fulfilled') setDownloads(items.value);
    if (system.status === 'fulfilled') {
      setStatus(system.value);
      setConnected(true);
    } else {
      setConnected(false);
    }
    if (captured.status === 'fulfilled') setCaptures(captured.value);
    if (nextSettings.status === 'fulfilled') setSettings(nextSettings.value);
    const failed = [items, system, captured, nextSettings].find((r) => r.status === 'rejected');
    if (failed) {
      const reason = (failed as PromiseRejectedResult).reason;
      setMessage(reason instanceof Error ? reason.message : 'Failed to load some data.');
    }
  }, []);

  useEffect(() => {
    refresh().catch((error: unknown) => setMessage(error instanceof Error ? error.message : 'Failed to load'));
    const timer = window.setInterval(() => refresh().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Supports the extension popup's "Open" action (?capture=<id>): scrolls to
  // and briefly highlights the matching capture once it has loaded, then
  // strips the query param so a page refresh doesn't re-trigger it.
  const scrolledToCaptureRef = useRef(false);
  useEffect(() => {
    if (scrolledToCaptureRef.current || captures.length === 0) return;
    const captureId = new URLSearchParams(window.location.search).get('capture');
    if (!captureId) return;
    const target = document.getElementById(`capture-${captureId}`);
    if (!target) return;
    scrolledToCaptureRef.current = true;
    if (target instanceof HTMLDetailsElement) target.open = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('highlighted');
    window.setTimeout(() => target.classList.remove('highlighted'), 3000);
    const url = new URL(window.location.href);
    url.searchParams.delete('capture');
    window.history.replaceState(null, '', url.toString());
  }, [captures]);

  async function addDownload(payload: DownloadCreateRequest) {
    await api.createDownload(payload);
    setMessage('Added to queue.');
    await refresh();
  }

  async function updateYtDlp() {
    setUpdating(true);
    try {
      const result = await api.updateYtDlp();
      setMessage(`yt-dlp updated: ${result.version ?? 'unknown'}`);
      await refresh();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Update failed');
    } finally {
      setUpdating(false);
    }
  }

  async function saveSettings(path: string) {
    setSettingsBusy(true);
    try {
      const next = await api.updateSettings(path);
      setSettings(next);
      setMessage('Download location updated.');
      return next;
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Unable to update download location');
      throw error;
    } finally {
      setSettingsBusy(false);
    }
  }

  async function resetSettings() {
    setSettingsBusy(true);
    try {
      const next = await api.resetDownloadDirectory();
      setSettings(next);
      setMessage('Download location reset to default.');
      return next;
    } finally {
      setSettingsBusy(false);
    }
  }

  async function openFolder() {
    setSettingsBusy(true);
    try {
      await api.openDownloadDirectory();
      setMessage('Opened download folder.');
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Unable to open download folder');
    } finally {
      setSettingsBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="eyebrow">LOCAL MEDIA DOWNLOADER</div>
          <h1>PocketDL</h1>
          <p>Browser capture + yt-dlp + FFmpeg, in one local app.</p>
        </div>
        <div className="topbar-actions">
          <div className="system-pill"><span className="dot" />{connected ? 'Backend connected' : 'Connecting…'}</div>
          <button className="secondary compact" onClick={() => setSettingsOpen((value) => !value)}>{settingsOpen ? 'Close settings' : 'Settings'}</button>
        </div>
      </header>

      {settingsOpen && settings && (
        <SettingsPanel
          value={settings}
          onSave={saveSettings}
          onReset={resetSettings}
          onOpen={openFolder}
          busy={settingsBusy}
        />
      )}

      <section className="panel hero-panel">
        <div className="section-heading">
          <div>
            <div className="eyebrow">QUICK DOWNLOAD</div>
            <h2>Paste a URL</h2>
          </div>
          <span className="section-note">Use Browser Capture for difficult HLS/DASH sites.</span>
        </div>
        <DownloadForm
          onSubmit={addDownload}
          onAnalyze={(payload): Promise<AnalyzeResponse> => api.analyze(payload)}
        />
        {message && <div className="message" role="status">{message}</div>}
      </section>

      <details className="section-collapsible" open>
        <summary className="section-collapsible-summary">
          <div>
            <div className="eyebrow">BROWSER CAPTURE</div>
            <h2>Captured streams</h2>
            <span>{captures.length} unique stream(s) · newest signed URL is kept automatically</span>
          </div>
          <span className="section-chevron">−</span>
        </summary>
        <CaptureList
          items={captures}
          onDownload={async (id: string, payload: CaptureDownloadRequest) => {
            await api.downloadCapture(id, payload);
            setMessage('Captured stream added to queue.');
            await refresh();
          }}
          onDelete={async (id: string) => {
            setCaptures((current) => current.filter((item) => item.id !== id));
            try {
              await api.deleteCapture(id);
            } catch (error: unknown) {
              setMessage(error instanceof Error ? error.message : 'Unable to remove capture');
            } finally {
              await refresh();
            }
          }}
        />
      </details>

      <details className="section-collapsible">
        <summary className="section-collapsible-summary">
          <div>
            <div className="eyebrow">INSTAGRAM</div>
            <h2>Profiles &amp; playlists</h2>
            <span>Browse a profile, save a selection, download it on demand</span>
          </div>
          <span className="section-chevron">−</span>
        </summary>
        <InstagramPanel onMessage={setMessage} onDownloadQueued={refresh} />
      </details>

      <details className="section-collapsible" open>
        <summary className="section-collapsible-summary">
          <div>
            <div className="eyebrow">DOWNLOAD QUEUE</div>
            <h2>Downloads</h2>
            <span>{downloads.length} item(s) · {status?.active_downloads ?? 0} active · {status?.queued_downloads ?? 0} queued</span>
          </div>
          <span className="section-chevron">−</span>
        </summary>
        <div className="section-toolbar-actions">
          <button className="secondary compact" disabled={updating} onClick={updateYtDlp}>
            {updating ? 'Updating…' : 'Update yt-dlp'}
          </button>
        </div>
        <DownloadList
          items={downloads}
          onCancel={async (id) => { await api.cancelDownload(id); await refresh(); }}
          onDelete={async (id) => {
            setDownloads((current) => current.filter((item) => item.id !== id));
            try {
              await api.deleteDownload(id);
            } catch (error: unknown) {
              setMessage(error instanceof Error ? error.message : 'Unable to remove download');
            } finally {
              await refresh();
            }
          }}
        />
      </details>

      <footer>
        <span className="footer-path">Downloads: {settings?.download_directory ?? 'Unavailable'}</span>
        <span>PocketDL v{status?.app_version ?? '0.2.3'}</span>
      </footer>
    </main>
  );
}
