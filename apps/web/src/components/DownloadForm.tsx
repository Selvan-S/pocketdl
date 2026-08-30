import { FormEvent, useState } from 'react';
import type { AnalyzeResponse, DownloadCreateRequest, DownloadPreset, DownloadPresetCreateRequest } from '../types/api';
import { AnalyzeResult } from './AnalyzeResult';

interface Props {
  onSubmit: (payload: DownloadCreateRequest) => Promise<void>;
  /** Queue several URLs at once (one per line in the URL box). Separate from
   * onSubmit because per-URL filename and format selection don't apply to a
   * batch -- each item derives its own. */
  onSubmitBatch: (payloads: DownloadCreateRequest[]) => Promise<void>;
  onAnalyze: (payload: { url: string; request_context: DownloadCreateRequest['request_context'] }) => Promise<AnalyzeResponse>;
  presets: DownloadPreset[];
  onSavePreset: (payload: DownloadPresetCreateRequest) => Promise<void>;
  onDeletePreset: (id: string) => Promise<void>;
}

/** Split the URL box into distinct, trimmed, non-empty lines. One line is a
 * normal single download; more than one triggers batch mode. */
export function parseUrls(raw: string): string[] {
  return Array.from(new Set(raw.split('\n').map((line) => line.trim()).filter(Boolean)));
}

export function DownloadForm({ onSubmit, onSubmitBatch, onAnalyze, presets, onSavePreset, onDeletePreset }: Props) {
  const [url, setUrl] = useState('');
  const [filename, setFilename] = useState('');
  const [preset, setPreset] = useState<DownloadCreateRequest['preset']>('best');
  const [concurrentFragments, setConcurrentFragments] = useState(8);
  const [retries, setRetries] = useState(10);
  const [useAria2, setUseAria2] = useState(false);
  const [subtitles, setSubtitles] = useState(false);
  const [subtitleLangs, setSubtitleLangs] = useState('en');
  const [embedSubtitles, setEmbedSubtitles] = useState(false);
  const [audioLanguage, setAudioLanguage] = useState('');
  const [conflictStrategy, setConflictStrategy] = useState<NonNullable<DownloadCreateRequest['conflict_strategy']>>('skip');
  const [presetName, setPresetName] = useState('');
  const [savingPreset, setSavingPreset] = useState(false);
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pageUrl, setPageUrl] = useState('');
  const [referer, setReferer] = useState('');
  const [origin, setOrigin] = useState('');
  const [userAgent, setUserAgent] = useState('');
  const [impersonation, setImpersonation] = useState<NonNullable<DownloadCreateRequest['request_context']>['impersonation']>('auto');
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [formatId, setFormatId] = useState<string | null>(null);

  /** Subtitle/audio options common to single and batch submissions. */
  function mediaOptions(): Partial<DownloadCreateRequest> {
    const options: Partial<DownloadCreateRequest> = {};
    if (subtitles) {
      options.subtitles = true;
      options.subtitle_langs = subtitleLangs.trim() || 'en';
      options.embed_subtitles = embedSubtitles;
    }
    if (audioLanguage.trim()) options.audio_language = audioLanguage.trim();
    if (conflictStrategy !== 'skip') options.conflict_strategy = conflictStrategy;
    return options;
  }

  function requestContext() {
    const context: DownloadCreateRequest['request_context'] = { impersonation };
    if (pageUrl.trim()) context.page_url = pageUrl.trim();
    if (referer.trim()) context.referer = referer.trim();
    if (origin.trim()) context.origin = origin.trim();
    if (userAgent.trim()) context.user_agent = userAgent.trim();
    return context;
  }

  async function handleAnalyze() {
    if (!url.trim()) return;
    setAnalyzing(true);
    try {
      const result = await onAnalyze({ url: url.trim(), request_context: requestContext() });
      setAnalysis(result);
      setFormatId(null);
      if (!filename.trim() && result.title) setFilename(result.title);
    } finally {
      setAnalyzing(false);
    }
  }

  const urls = parseUrls(url);
  const isBatch = urls.length > 1;

  function applyPreset(id: string) {
    const chosen = presets.find((item) => item.id === id);
    if (!chosen) return;
    setPreset(chosen.preset);
    setConcurrentFragments(chosen.concurrent_fragments);
    setRetries(chosen.retries);
    setUseAria2(chosen.use_aria2);
    // Format_id is URL-specific, so applying a preset clears any earlier pick.
    setFormatId(null);
  }

  async function saveCurrentAsPreset() {
    const name = presetName.trim();
    if (!name) return;
    setSavingPreset(true);
    try {
      await onSavePreset({
        name,
        preset: preset ?? 'best',
        concurrent_fragments: concurrentFragments,
        retries,
        use_aria2: useAria2,
      });
      setPresetName('');
    } finally {
      setSavingPreset(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (urls.length === 0) return;
    setBusy(true);
    try {
      if (isBatch) {
        // Batch: preset + performance knobs + request context apply to every
        // URL; filename and format_id are single-item concerns and skipped.
        await onSubmitBatch(
          urls.map((one) => ({
            url: one,
            preset,
            concurrent_fragments: concurrentFragments,
            retries,
            use_aria2: useAria2,
            ...mediaOptions(),
            request_context: requestContext(),
          })),
        );
      } else {
        const payload: DownloadCreateRequest = {
          url: urls[0],
          preset,
          concurrent_fragments: concurrentFragments,
          retries,
          use_aria2: useAria2,
          ...mediaOptions(),
          request_context: requestContext(),
        };
        if (filename.trim()) payload.filename = filename.trim();
        if (formatId) payload.format_id = formatId;
        await onSubmit(payload);
      }
      setUrl('');
      setFilename('');
      setAnalysis(null);
      setFormatId(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="download-form" onSubmit={handleSubmit}>
      <label htmlFor="url">Video URL <span className="hint">(one per line to queue several)</span></label>
      <textarea
        id="url"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="Paste a video page or m3u8 URL — or several, one per line"
        rows={3}
        autoCapitalize="none"
        autoCorrect="off"
      />

      <div className="action-row">
        <button type="button" className="secondary" disabled={analyzing || busy || urls.length !== 1} onClick={handleAnalyze}>
          {analyzing ? 'Analyzing…' : 'Analyze'}
        </button>
        <button disabled={busy || analyzing || urls.length === 0} type="submit">
          {busy ? 'Adding…' : isBatch ? `Download ${urls.length}` : 'Download'}
        </button>
      </div>
      {isBatch && (
        <div className="field-help">
          {urls.length} URLs detected — they&apos;ll be queued at the preset above. File name and format
          selection apply to a single URL only and are skipped in batch mode.
        </div>
      )}

      <label htmlFor="filename">File name <span className="hint">(optional)</span></label>
      <input
        id="filename"
        value={filename}
        onChange={(event) => setFilename(event.target.value)}
        placeholder="Analyze first to use the extracted title"
        maxLength={200}
        autoComplete="off"
      />
      <div className="field-help">The extension is selected automatically from the downloaded format.</div>

      <div className="row">
        <select value={preset} disabled={!!formatId} onChange={(event) => setPreset(event.target.value as DownloadCreateRequest['preset'])}>
          <option value="best">Best quality</option>
          <option value="1080p">Up to 1080p</option>
          <option value="720p">Up to 720p</option>
          <option value="480p">Up to 480p</option>
          <option value="audio">Audio only</option>
        </select>
        {presets.length > 0 && (
          <select value="" onChange={(event) => { applyPreset(event.target.value); event.target.value = ''; }} aria-label="Apply a saved preset">
            <option value="">Apply a preset…</option>
            {presets.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        )}
      </div>

      <button type="button" className="advanced-toggle" onClick={() => setAdvancedOpen((value) => !value)}>
        {advancedOpen ? 'Hide request options' : 'Advanced request options'}
      </button>

      {advancedOpen && (
        <div className="advanced-panel">
          <div className="field-help">Performance</div>
          <div className="row">
            <label htmlFor="concurrent-fragments">Concurrent fragments
              <input id="concurrent-fragments" type="number" min={1} max={32} value={concurrentFragments}
                onChange={(event) => setConcurrentFragments(Math.max(1, Math.min(32, Number(event.target.value) || 1)))} />
            </label>
            <label htmlFor="retries">Retries
              <input id="retries" type="number" min={1} max={100} value={retries}
                onChange={(event) => setRetries(Math.max(1, Math.min(100, Number(event.target.value) || 1)))} />
            </label>
          </div>
          <label className="checkbox-chip">
            <input type="checkbox" checked={useAria2} onChange={(event) => setUseAria2(event.target.checked)} />
            Use aria2 for direct downloads (when available)
          </label>

          <div className="field-help">Subtitles &amp; audio</div>
          <label className="checkbox-chip">
            <input type="checkbox" checked={subtitles} onChange={(event) => setSubtitles(event.target.checked)} />
            Download subtitles/captions
          </label>
          {subtitles && (
            <div className="row">
              <label htmlFor="sub-langs">Languages
                <input id="sub-langs" value={subtitleLangs} onChange={(event) => setSubtitleLangs(event.target.value)} placeholder="en,es or all" maxLength={100} />
              </label>
              <label className="checkbox-chip">
                <input type="checkbox" checked={embedSubtitles} onChange={(event) => setEmbedSubtitles(event.target.checked)} />
                Embed into video
              </label>
            </div>
          )}
          <label htmlFor="audio-language">Preferred audio language <span className="hint">(optional)</span>
            <input id="audio-language" value={audioLanguage} onChange={(event) => setAudioLanguage(event.target.value)} placeholder="e.g. en, pt-BR" maxLength={20} />
          </label>

          <label htmlFor="conflict-strategy">If the file already exists
            <select id="conflict-strategy" value={conflictStrategy} onChange={(event) => setConflictStrategy(event.target.value as typeof conflictStrategy)}>
              <option value="skip">Skip (keep existing)</option>
              <option value="rename">Rename (keep both)</option>
              <option value="overwrite">Overwrite</option>
            </select>
          </label>

          <div className="field-help">Save the current quality + performance settings as a reusable preset.</div>
          <div className="row">
            <input value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Preset name" maxLength={100} />
            <button type="button" className="secondary" disabled={savingPreset || !presetName.trim()} onClick={() => void saveCurrentAsPreset()}>
              {savingPreset ? 'Saving…' : 'Save as preset'}
            </button>
          </div>
          {presets.length > 0 && (
            <ul className="preset-list">
              {presets.map((item) => (
                <li key={item.id}>
                  <span>{item.name} <small>({item.preset})</small></span>
                  <button type="button" className="link-button" onClick={() => void onDeletePreset(item.id)}>Delete</button>
                </li>
              ))}
            </ul>
          )}

          <div className="field-help">Use these when a site needs the same browser request context as the player. Values are sent only to your local PocketDL backend.</div>
          <label htmlFor="page-url">Page URL</label>
          <input id="page-url" value={pageUrl} onChange={(event) => setPageUrl(event.target.value)} placeholder="https://example.com/video-page" />
          <label htmlFor="referer">Referer</label>
          <input id="referer" value={referer} onChange={(event) => setReferer(event.target.value)} placeholder="https://example.com/" />
          <label htmlFor="origin">Origin</label>
          <input id="origin" value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="https://example.com" />
          <label htmlFor="user-agent">User-Agent</label>
          <input id="user-agent" value={userAgent} onChange={(event) => setUserAgent(event.target.value)} placeholder="Mozilla/5.0 ..." />
          <label htmlFor="impersonation">Browser impersonation</label>
          <select id="impersonation" value={impersonation} onChange={(event) => setImpersonation(event.target.value as typeof impersonation)}>
            <option value="auto">Auto</option>
            <option value="chrome">Chrome</option>
            <option value="none">None</option>
          </select>
        </div>
      )}

      {analysis && (
        <AnalyzeResult result={analysis} selectedFormatId={formatId} onSelectFormat={setFormatId} />
      )}
    </form>
  );
}
