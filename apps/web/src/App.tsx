import { useCallback, useEffect, useRef, useState } from 'react';
import { api, EVENTS_URL } from './api/client';
import { DownloadForm } from './components/DownloadForm';
import { DownloadList } from './components/DownloadList';
import { CaptureList } from './components/CaptureList';
import { InstagramPanel } from './components/InstagramPanel';
import { SettingsPanel } from './components/SettingsPanel';
import type { AnalyzeResponse, CaptureDownloadRequest, CaptureItem, Collection, DownloadCreateRequest, DownloadItem, DownloadPreset, DownloadPresetCreateRequest, ServerStateEvent, SettingsResponse, SystemStatus } from './types/api';
import {
  collectionsThatCompleted,
  completionMap,
  downloadsThatFinished,
  statusMap,
  type StatusMap,
} from './lib/notifications';
import './styles.css';

const NOTIFICATIONS_STORAGE_KEY = 'pocketdl.notifications';

/** Structural equality by serialisation. The payloads here are small,
 * JSON-derived, and compared once per pushed frame, so this is cheaper than
 * the re-render it avoids -- and unlike a hand-written comparison it cannot
 * go stale when a field is added to the API. */
function sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function App() {
  const [downloads, setDownloads] = useState<DownloadItem[]>([]);
  const [captures, setCaptures] = useState<CaptureItem[]>([]);
  // Collection summaries (counts, not items) live here rather than inside the
  // Instagram panel so the SSE snapshot can keep them live -- an item
  // finishing its download moves the playlist's Downloaded badge without a
  // reload. The panel re-fetches an open playlist's items when these counts
  // change; see PlaylistCard.
  const [collections, setCollections] = useState<Collection[]>([]);
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
  const [presets, setPresets] = useState<DownloadPreset[]>([]);
  const [notificationsEnabled, setNotificationsEnabled] = useState(() => {
    try {
      return localStorage.getItem(NOTIFICATIONS_STORAGE_KEY) === 'on';
    } catch {
      return false;
    }
  });

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
    const [items, system, captured, nextSettings, nextCollections] = await Promise.allSettled([
      api.listDownloads(),
      api.status(),
      api.listCaptures(),
      api.settings(),
      api.listCollections(),
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
    if (nextCollections.status === 'fulfilled') setCollections(nextCollections.value);
    const failed = [items, system, captured, nextSettings, nextCollections].find((r) => r.status === 'rejected');
    if (failed) {
      const reason = (failed as PromiseRejectedResult).reason;
      setMessage(reason instanceof Error ? reason.message : 'Failed to load some data.');
    }
  }, []);

  // Applies a pushed snapshot, but only where something actually differs.
  // Returning the previous array unchanged makes React bail out of the
  // re-render entirely -- the old 2s poll replaced these arrays on every
  // tick, so the download and capture lists re-rendered constantly even
  // when idle, which is a large part of why the page felt sluggish.
  const applyServerState = useCallback((snapshot: ServerStateEvent) => {
    setConnected(true);
    if (snapshot.downloads) setDownloads((current) => (sameJson(current, snapshot.downloads) ? current : snapshot.downloads!));
    if (snapshot.captures) setCaptures((current) => (sameJson(current, snapshot.captures) ? current : snapshot.captures!));
    if (snapshot.status) setStatus((current) => (sameJson(current, snapshot.status) ? current : snapshot.status));
    if (snapshot.settings) setSettings((current) => (sameJson(current, snapshot.settings) ? current : snapshot.settings));
    if (snapshot.collections) setCollections((current) => (sameJson(current, snapshot.collections) ? current : snapshot.collections!));
  }, []);

  useEffect(() => {
    // Seed the UI immediately; the stream's first frame arrives a moment
    // later and is deduped against this by applyServerState.
    refresh().catch((error: unknown) => setMessage(error instanceof Error ? error.message : 'Failed to load'));

    let pollTimer: number | undefined;
    const startPolling = () => {
      if (pollTimer === undefined) pollTimer = window.setInterval(() => refresh().catch(() => undefined), 2000);
    };
    const stopPolling = () => {
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
      pollTimer = undefined;
    };

    if (typeof EventSource === 'undefined') {
      startPolling();
      return () => stopPolling();
    }

    const source = new EventSource(EVENTS_URL);
    source.addEventListener('state', (event) => {
      // A working stream makes the fallback poll redundant.
      stopPolling();
      try {
        applyServerState(JSON.parse((event as MessageEvent<string>).data) as ServerStateEvent);
      } catch {
        // A malformed frame is not worth tearing the stream down over; the
        // next one carries the same full snapshot.
      }
    });
    source.onerror = () => {
      // EventSource reconnects on its own, but the backend may also be
      // genuinely down -- poll meanwhile so the UI still recovers, and stop
      // again as soon as a frame arrives.
      setConnected(false);
      startPolling();
    };

    return () => {
      source.close();
      stopPolling();
    };
  }, [refresh, applyServerState]);

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

  // Fire a desktop notification when a download or a whole playlist finishes,
  // if the user opted in and granted permission. The detection is pure and
  // tested (lib/notifications); here we only diff each incoming snapshot
  // against the previous one. The refs seed silently on first paint so an
  // app opened with already-finished items doesn't fire a burst.
  const prevDownloadStatuses = useRef<StatusMap>(new Map());
  const downloadsSeeded = useRef(false);
  const prevCollectionCompletion = useRef<Map<string, boolean>>(new Map());
  const collectionsSeeded = useRef(false);

  const notify = useCallback((title: string, body: string) => {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    try {
      new Notification(title, { body });
    } catch {
      // Some browsers throw if constructed outside a service worker; ignore.
    }
  }, []);

  useEffect(() => {
    if (downloadsSeeded.current && notificationsEnabled) {
      for (const finished of downloadsThatFinished(prevDownloadStatuses.current, downloads)) {
        const job = downloads.find((item) => item.id === finished.id);
        const label = job?.title || job?.filename || job?.url || 'Download';
        notify(finished.status === 'completed' ? 'Download complete' : 'Download failed', label);
      }
    }
    prevDownloadStatuses.current = statusMap(downloads);
    downloadsSeeded.current = true;
  }, [downloads, notificationsEnabled, notify]);

  useEffect(() => {
    if (collectionsSeeded.current && notificationsEnabled) {
      for (const done of collectionsThatCompleted(prevCollectionCompletion.current, collections)) {
        notify('Playlist complete', `${done.name} — ${done.item_count} item(s)`);
      }
    }
    prevCollectionCompletion.current = completionMap(collections);
    collectionsSeeded.current = true;
  }, [collections, notificationsEnabled, notify]);

  async function toggleNotifications() {
    if (notificationsEnabled) {
      setNotificationsEnabled(false);
      try { localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, 'off'); } catch { /* ignore */ }
      return;
    }
    if (typeof Notification === 'undefined') {
      setMessage('Notifications are not supported in this browser.');
      return;
    }
    let permission = Notification.permission;
    if (permission === 'default') permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      setMessage('Notification permission was not granted.');
      return;
    }
    setNotificationsEnabled(true);
    try { localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, 'on'); } catch { /* ignore */ }
    setMessage('You’ll be notified when downloads finish.');
  }

  // Presets change only on an explicit user action, so they are fetched on
  // mount and re-fetched after a save/delete rather than riding the 2s poll
  // or the SSE snapshot.
  const refreshPresets = useCallback(async () => {
    try {
      setPresets(await api.listPresets());
    } catch {
      // Non-critical: the form just won't offer saved presets this session.
    }
  }, []);

  useEffect(() => { void refreshPresets(); }, [refreshPresets]);

  async function savePreset(payload: DownloadPresetCreateRequest) {
    try {
      await api.createPreset(payload);
      setMessage(`Saved preset “${payload.name}”.`);
      await refreshPresets();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Unable to save preset');
    }
  }

  async function deletePreset(id: string) {
    try {
      await api.deletePreset(id);
      await refreshPresets();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete preset');
    }
  }

  async function addDownload(payload: DownloadCreateRequest) {
    await api.createDownload(payload);
    setMessage('Added to queue.');
    await refresh();
  }

  async function addDownloadBatch(payloads: DownloadCreateRequest[]) {
    let added = 0;
    const failed: string[] = [];
    // Sequential rather than Promise.all: the queue accepts them instantly
    // (it dispatches its own workers), and one bad URL shouldn't abort the
    // rest. Refresh once at the end instead of per item.
    for (const payload of payloads) {
      try {
        await api.createDownload(payload);
        added += 1;
      } catch {
        failed.push(payload.url);
      }
    }
    setMessage(failed.length === 0 ? `Queued ${added} download(s).` : `Queued ${added}, ${failed.length} failed.`);
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

  async function browseDownloadDirectory(): Promise<string | null> {
    try {
      const result = await api.browseDownloadDirectory();
      return result.path;
    } catch (error: unknown) {
      // Expected on Termux/headless environments (no display for a native
      // folder dialog) -- surfaced as a message, not treated as a crash.
      setMessage(error instanceof Error ? error.message : 'Unable to open the folder picker.');
      return null;
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
          onBrowse={browseDownloadDirectory}
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
          onSubmitBatch={addDownloadBatch}
          onAnalyze={(payload): Promise<AnalyzeResponse> => api.analyze(payload)}
          presets={presets}
          onSavePreset={savePreset}
          onDeletePreset={deletePreset}
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
        <InstagramPanel
          collections={collections}
          onCollectionsChanged={refresh}
          onMessage={setMessage}
          onDownloadQueued={refresh}
        />
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
          <button className="secondary compact" onClick={() => void toggleNotifications()}>
            {notificationsEnabled ? 'Notifications: on' : 'Notify when done'}
          </button>
          <button className="secondary compact" disabled={updating} onClick={updateYtDlp}>
            {updating ? 'Updating…' : 'Update yt-dlp'}
          </button>
        </div>
        <DownloadList
          items={downloads}
          onCancel={async (id) => { await api.cancelDownload(id); await refresh(); }}
          onRetry={async (id) => {
            try {
              await api.retryDownload(id);
              setMessage('Retrying download…');
            } catch (error: unknown) {
              setMessage(error instanceof Error ? error.message : 'Unable to retry download');
            } finally {
              await refresh();
            }
          }}
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
