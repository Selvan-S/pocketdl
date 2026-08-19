import { FormEvent, useState } from 'react';
import type { AnalyzeResponse, DownloadCreateRequest } from '../types/api';
import { AnalyzeResult } from './AnalyzeResult';

interface Props {
  onSubmit: (payload: DownloadCreateRequest) => Promise<void>;
  onAnalyze: (payload: { url: string; request_context: DownloadCreateRequest['request_context'] }) => Promise<AnalyzeResponse>;
}

export function DownloadForm({ onSubmit, onAnalyze }: Props) {
  const [url, setUrl] = useState('');
  const [filename, setFilename] = useState('');
  const [preset, setPreset] = useState<DownloadCreateRequest['preset']>('best');
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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    try {
      const payload: DownloadCreateRequest = {
        url: url.trim(),
        preset,
        concurrent_fragments: 8,
        retries: 10,
        use_aria2: false,
        request_context: requestContext(),
      };
      if (filename.trim()) payload.filename = filename.trim();
      if (formatId) payload.format_id = formatId;
      await onSubmit(payload);
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
      <label htmlFor="url">Video URL</label>
      <textarea
        id="url"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="Paste a video page or m3u8 URL"
        rows={3}
        autoCapitalize="none"
        autoCorrect="off"
      />

      <div className="action-row">
        <button type="button" className="secondary" disabled={analyzing || busy || !url.trim()} onClick={handleAnalyze}>
          {analyzing ? 'Analyzing…' : 'Analyze'}
        </button>
        <button disabled={busy || analyzing || !url.trim()} type="submit">
          {busy ? 'Adding…' : 'Download'}
        </button>
      </div>

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
      </div>

      <button type="button" className="advanced-toggle" onClick={() => setAdvancedOpen((value) => !value)}>
        {advancedOpen ? 'Hide request options' : 'Advanced request options'}
      </button>

      {advancedOpen && (
        <div className="advanced-panel">
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
