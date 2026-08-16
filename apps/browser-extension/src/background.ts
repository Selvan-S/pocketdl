import { EXTENSION_PROTOCOL_HEADER, getBackendUrl } from './config.js';
import type { CaptureType, PendingRequest } from './models.js';

const pending = new Map<string, PendingRequest>();
const recentCaptureKeys = new Map<string, number>();
const MAX_PENDING = 500;
const CAPTURE_COOLDOWN_MS = 8_000;
const manifestTabs = new Set<number>();

function headerValue(headers: chrome.webRequest.HttpHeader[] | undefined, name: string): string | undefined {
  return headers?.find((header) => header.name.toLowerCase() === name.toLowerCase())?.value;
}

function captureTypeFromUrl(url: string): CaptureType | null {
  if (/\.m3u8(?:$|[?#])/i.test(url)) return 'hls';
  if (/\.mpd(?:$|[?#])/i.test(url)) return 'dash';
  if (/\.(?:mp4|m4v|webm|mov|mkv|ts|m4s)(?:$|[?#])/i.test(url)) return 'media';
  if (/\.(?:mp3|m4a|aac|wav|ogg|opus)(?:$|[?#])/i.test(url)) return 'media';
  return null;
}

function captureTypeFromContentType(contentType: string | undefined): CaptureType | null {
  const value = contentType?.split(';', 1)[0].trim().toLowerCase();
  if (!value) return null;
  if (value === 'application/vnd.apple.mpegurl' || value === 'application/x-mpegurl' || value.includes('mpegurl')) return 'hls';
  if (value === 'application/dash+xml') return 'dash';
  if (value.startsWith('video/') || value.startsWith('audio/')) return 'media';
  return null;
}


function isLikelyMediaSegment(url: string): boolean {
  return /\/(?:segment|segments|chunk|chunks|fragment|fragments|init|init-segment|parts?)\b/i.test(url)
    || /\.(?:m4s|cmfv|cmfa|ts)(?:$|[?#])/i.test(url)
    || /(?:[?&](?:segment|chunk|fragment|part|range)=|[?&](?:seg|chunk|frag)=)/i.test(url);
}

function contentLength(headers: chrome.webRequest.HttpHeader[] | undefined): number | undefined {
  const value = headerValue(headers, 'content-length');
  if (!value) return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function shouldCaptureUrl(url: string, requestType?: string): CaptureType | null {
  return captureTypeFromUrl(url) ?? (requestType === 'media' ? 'media' : null);
}

function shouldDeduplicate(tabId: number, url: string): boolean {
  if (tabId < 0) return true;
  const normalized = url.split('#', 1)[0];
  const key = `${tabId}:${normalized}`;
  const previous = recentCaptureKeys.get(key);
  if (previous && Date.now() - previous < CAPTURE_COOLDOWN_MS) return false;
  recentCaptureKeys.set(key, Date.now());
  if (recentCaptureKeys.size > 1000) {
    const cutoff = Date.now() - CAPTURE_COOLDOWN_MS;
    for (const [captureKey, timestamp] of recentCaptureKeys) {
      if (timestamp < cutoff) recentCaptureKeys.delete(captureKey);
    }
  }
  return true;
}

function safeHeaderMap(headers: chrome.webRequest.HttpHeader[] | undefined): Record<string, string> {
  const result: Record<string, string> = {};
  for (const header of headers ?? []) {
    const name = header.name.trim();
    if (!name || !header.value) continue;
    const normalized = name.toLowerCase();
    if (normalized === 'cookie' || normalized === 'authorization' || normalized === 'proxy-authorization' || normalized === 'set-cookie') continue;
    result[name] = header.value;
  }
  return result;
}

async function enrichRequest(requestId: string, details: chrome.webRequest.OnBeforeSendHeadersDetails): Promise<void> {
  const item = pending.get(requestId);
  if (!item) return;
  item.headers = { ...item.headers, ...safeHeaderMap(details.requestHeaders) };
  if (!item.pageUrl || !item.pageTitle) {
    try {
      const tab = await chrome.tabs.get(item.tabId);
      item.pageUrl ??= tab.url;
      item.pageTitle ??= tab.title;
    } catch {
      // The tab may already be closed.
    }
  }
}

async function enrichResponse(requestId: string, details: chrome.webRequest.OnHeadersReceivedDetails): Promise<void> {
  const existing = pending.get(requestId);
  const contentType = headerValue(details.responseHeaders, 'content-type');
  const sizeBytes = contentLength(details.responseHeaders);
  if (existing) {
    existing.contentType = contentType ?? existing.contentType;
    existing.captureType = existing.captureType || captureTypeFromContentType(contentType) || 'media';
    existing.contentLengthBytes = sizeBytes ?? existing.contentLengthBytes;
    if (existing.captureType === 'hls' || existing.captureType === 'dash') {
      manifestTabs.add(existing.tabId);
    }
    return;
  }

  const captureType = captureTypeFromContentType(contentType);
  if (!captureType || details.tabId < 0 || !shouldDeduplicate(details.tabId, details.url)) return;
  if (captureType === 'media' && (manifestTabs.has(details.tabId) || isLikelyMediaSegment(details.url))) return;

  const item: PendingRequest = {
    url: details.url,
    tabId: details.tabId,
    headers: {},
    captureType,
    contentType,
    contentLengthBytes: sizeBytes,
  };
  if (captureType === 'hls' || captureType === 'dash') {
    manifestTabs.add(details.tabId);
  }
  pending.set(requestId, item);
  try {
    const tab = await chrome.tabs.get(details.tabId);
    item.pageUrl = tab.url;
    item.pageTitle = tab.title;
  } catch {
    // Best effort only.
  }
}

async function sendCapture(requestId: string, statusCode: number): Promise<void> {
  const item = pending.get(requestId);
  pending.delete(requestId);
  if (!item || statusCode < 200 || statusCode >= 400) return;

  const backendUrl = await getBackendUrl();
  const headers = item.headers;
  const referer = headerValue(Object.entries(headers).map(([name, value]) => ({ name, value })), 'referer');
  const origin = headerValue(Object.entries(headers).map(([name, value]) => ({ name, value })), 'origin');
  const userAgent = headerValue(Object.entries(headers).map(([name, value]) => ({ name, value })), 'user-agent');

  try {
    await fetch(`${backendUrl}/api/captures`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-PocketDL-Extension': EXTENSION_PROTOCOL_HEADER,
      },
      body: JSON.stringify({
        media_url: item.url,
        page_url: item.pageUrl ?? null,
        page_title: item.pageTitle ?? null,
        referer: referer ?? null,
        origin: origin ?? null,
        user_agent: userAgent ?? null,
        headers,
        capture_type: item.captureType,
        content_type: item.contentType ?? null,
        content_length_bytes: item.contentLengthBytes ?? null,
      }),
    });
  } catch {
    // PocketDL may be offline; the popup can show connection state later.
  }
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    const type = shouldCaptureUrl(details.url, details.type);
    if (!type || details.tabId < 0 || !shouldDeduplicate(details.tabId, details.url)) return;
    if (type === 'media' && (manifestTabs.has(details.tabId) || isLikelyMediaSegment(details.url))) return;
    if (pending.size >= MAX_PENDING) {
      const oldest = pending.keys().next().value;
      if (oldest) pending.delete(oldest);
    }

    const item: PendingRequest = {
      url: details.url,
      tabId: details.tabId,
      headers: {},
      captureType: type,
    };
    pending.set(details.requestId, item);
    void chrome.tabs.get(details.tabId).then((tab) => {
      const current = pending.get(details.requestId);
      if (!current) return;
      current.pageUrl ??= tab.url;
      current.pageTitle ??= tab.title;
    }).catch(() => undefined);
  },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other'] },
);

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => { void enrichRequest(details.requestId, details); },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other'] },
  ['requestHeaders', 'extraHeaders'],
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => { void enrichResponse(details.requestId, details); },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other'] },
  ['responseHeaders'],
);

chrome.webRequest.onCompleted.addListener(
  (details) => { void sendCapture(details.requestId, details.statusCode); },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other'] },
);

chrome.webRequest.onErrorOccurred.addListener(
  (details) => { pending.delete(details.requestId); },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other'] },
);


chrome.tabs.onRemoved.addListener((tabId) => {
  manifestTabs.delete(tabId);
  for (const key of recentCaptureKeys.keys()) {
    if (key.startsWith(`${tabId}:`)) recentCaptureKeys.delete(key);
  }
});
