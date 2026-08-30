import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  Collection,
  CollectionItem,
  CollectionItemState,
  InstagramContentType,
  InstagramProfilePreviewRequest,
  InstagramSessionStatus,
  ProfileItemPreview,
} from '../types/api';

// How many playlist rows to render per page. A playlist can hold hundreds of
// items; rendering them all at once is exactly the "one unbroken scroll"
// Round 10 set out to fix.
const PLAYLIST_PAGE_SIZE = 24;

const PLAYLIST_TABS: Array<{ value: CollectionItemState; label: string }> = [
  { value: 'pending', label: 'Pending' },
  { value: 'downloaded', label: 'Downloaded' },
  { value: 'all', label: 'All' },
];

interface Props {
  // Summaries (counts, not items) owned by App and kept live off the SSE
  // snapshot, so a playlist's badge moves when a download finishes without a
  // reload. onCollectionsChanged re-seeds them immediately after a local
  // mutation rather than waiting for the next pushed frame.
  collections: Collection[];
  onCollectionsChanged: () => Promise<void>;
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}

// Ceiling for "Add all matching". The server clamps to this too; it is
// stated here so the UI can say what it stopped at rather than silently
// adding a subset. Sized so one request still fits the backend's budget --
// see _MAX_PAGE_SIZE in instaloader_service.py.
const BULK_ADD_LIMIT = 200;

// Initial preview page size, kept small on purpose. Each selected content
// type is fetched separately, and Instagram rate-limits automated access
// hard, so a full-profile preview at the old default (50 per type) could be
// a dozen+ requests and risk a temporary account restriction. "Load older
// items" pages more only when the user asks.
const PREVIEW_PAGE_SIZE = 12;

const CONTENT_TYPES: Array<{ value: InstagramContentType; label: string }> = [
  { value: 'post', label: 'Posts' },
  { value: 'reel', label: 'Reels' },
  { value: 'story', label: 'Stories' },
  { value: 'highlight', label: 'Highlights' },
];

// <input type="date"> yields a bare "YYYY-MM-DD"; widen it to that day's UTC
// boundaries so the backend's since/until comparison (against tz-aware
// post_date values, see InstaloaderService) gets a tz-aware datetime rather
// than a naive one, and so "posted before <date>" still includes that date.
function dateInputToRangeStart(value: string): string | undefined {
  return value ? `${value}T00:00:00.000Z` : undefined;
}

function dateInputToRangeEnd(value: string): string | undefined {
  return value ? `${value}T23:59:59.999Z` : undefined;
}

function formatPostedAt(postedAt: string | null): string | null {
  if (!postedAt) return null;
  const parsed = new Date(postedAt);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function InstagramPanel({ collections, onCollectionsChanged, onMessage, onDownloadQueued }: Props) {
  const [session, setSession] = useState<InstagramSessionStatus | null>(null);

  useEffect(() => {
    api.instagramSessionStatus().then(setSession).catch(() => undefined);
  }, []);

  return (
    <div className="instagram-panel">
      <div className="instagram-warning" role="note">
        <strong>Instagram rate-limits automated access.</strong> To avoid a temporary account restriction:
        prefer a secondary account, preview a small batch (this loads {PREVIEW_PAGE_SIZE} per type and pages more only when you ask),
        add a date range for large profiles, and don’t browse or download a lot in quick succession.
      </div>
      <SessionControl session={session} onChange={setSession} onMessage={onMessage} />
      <ProfileBrowser collections={collections} onCollectionsChanged={onCollectionsChanged} onMessage={onMessage} />
      <PlaylistsView
        collections={collections}
        onCollectionsChanged={onCollectionsChanged}
        onMessage={onMessage}
        onDownloadQueued={onDownloadQueued}
      />
    </div>
  );
}

function SessionControl({
  session,
  onChange,
  onMessage,
}: {
  session: InstagramSessionStatus | null;
  onChange: (session: InstagramSessionStatus) => void;
  onMessage: (message: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [cookie, setCookie] = useState('');
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const value = cookie.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.setInstagramSession(value);
      onChange(next);
      setCookie('');
      setExpanded(false);
      onMessage(
        next.verified_username
          ? `Instagram session saved -- verified as @${next.verified_username}.`
          : 'Instagram session saved, but verification failed. Double-check the cookie is current.',
      );
    } catch (caughtError) {
      // Also shown inline (not just via onMessage) since the shared message
      // banner lives at the top of the page, far from this form.
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to save the session cookie.';
      setError(text);
      onMessage(text);
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setVerifying(true);
    setError(null);
    try {
      const next = await api.verifyInstagramSession();
      onChange(next);
      onMessage(next.verified_username ? `Session verified as @${next.verified_username}.` : 'Session verification failed.');
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to verify the session.';
      setError(text);
      onMessage(text);
    } finally {
      setVerifying(false);
    }
  }

  async function clear() {
    setBusy(true);
    try {
      await api.clearInstagramSession();
      onChange({ configured: false, verified_username: null });
      onMessage('Instagram session cleared.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="instagram-session">
      <div className="instagram-session-status">
        <span className={`status-badge ${session?.configured ? 'used' : ''}`}>
          {session?.configured
            ? session.verified_username
              ? `Verified as @${session.verified_username}`
              : 'Session configured (unverified)'
            : 'No session configured'}
        </span>
        {session?.configured && (
          <button type="button" className="link-button" disabled={verifying} onClick={() => void verify()}>
            {verifying ? 'Verifying…' : 'Verify'}
          </button>
        )}
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setExpanded((value) => !value);
            setError(null);
          }}
        >
          {expanded ? 'Cancel' : session?.configured ? 'Replace session' : 'Add session cookie'}
        </button>
        {session?.configured && (
          <button type="button" className="link-button" disabled={busy} onClick={() => void clear()}>
            Clear
          </button>
        )}
      </div>
      {expanded && (
        <div className="instagram-session-form">
          <label>
            Paste your browser&apos;s Cookie header for instagram.com, or a JSON cookie export
            <textarea
              value={cookie}
              onChange={(event) => setCookie(event.target.value)}
              placeholder={'sessionid=...; csrftoken=...;\nor: [{"name":"sessionid","value":"..."}, ...]'}
            />
          </label>
          <div className="field-help">
            Never a password. Either the raw <code>Cookie:</code> header value from DevTools, or an export from a
            cookie-manager extension (Cookie-Editor, EditThisCookie, etc.) for instagram.com. Only from your own
            already signed-in browser, used to browse profiles you can already access. Stored locally, never shown
            again.
          </div>
          {error && <div className="error">{error}</div>}
          <button disabled={busy || !cookie.trim()} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save session'}
          </button>
        </div>
      )}
    </div>
  );
}

function ProfileBrowser({
  collections,
  onCollectionsChanged,
  onMessage,
}: {
  collections: Collection[];
  onCollectionsChanged: () => Promise<void>;
  onMessage: (message: string) => void;
}) {
  const [profileUrl, setProfileUrl] = useState('');
  const [selectedTypes, setSelectedTypes] = useState<InstagramContentType[]>(['post', 'reel']);
  const [postedAfter, setPostedAfter] = useState('');
  const [postedBefore, setPostedBefore] = useState('');
  const [items, setItems] = useState<ProfileItemPreview[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [targetCollectionId, setTargetCollectionId] = useState('');
  const [newCollectionName, setNewCollectionName] = useState('');
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set from the previous page's response; drives "Load more".
  const [nextPostedBefore, setNextPostedBefore] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // The query the current results came from. "Add all matching" re-runs it
  // server-side, so it must be what was actually asked for, not whatever the
  // form has been edited to since.
  const [lastQuery, setLastQuery] = useState<InstagramProfilePreviewRequest | null>(null);
  // "Add all matching" pages the profile in BULK_ADD_LIMIT chunks. These
  // remember where the last chunk stopped so "Add next batch" can continue
  // walking backward through the whole profile without the user typing dates.
  const [syncCollectionId, setSyncCollectionId] = useState<string | null>(null);
  const [syncCursor, setSyncCursor] = useState<string | null>(null);
  const [syncHasMore, setSyncHasMore] = useState(false);
  const [syncTotalAdded, setSyncTotalAdded] = useState(0);

  function resetSync() {
    setSyncCollectionId(null);
    setSyncCursor(null);
    setSyncHasMore(false);
    setSyncTotalAdded(0);
  }

  // A playlist the user picked can be deleted from the panel below, leaving
  // this holding an id that no longer exists. The <select> then falls back to
  // displaying its first option ("New playlist...") while the state still says
  // otherwise, so the name field stayed hidden and there was no way to create
  // a playlist at all.
  useEffect(() => {
    if (targetCollectionId && !collections.some((collection) => collection.id === targetCollectionId)) {
      setTargetCollectionId('');
    }
  }, [collections, targetCollectionId]);

  function toggleType(type: InstagramContentType) {
    setSelectedTypes((current) => (current.includes(type) ? current.filter((value) => value !== type) : [...current, type]));
  }

  function toggleSelected(url: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  const allLoadedSelected = items.length > 0 && selected.size === items.length;

  function toggleSelectAll() {
    // Deliberately scoped to what is loaded. Selecting items the user has
    // not seen is what "Add all matching" is for, and that runs server-side
    // rather than pretending a hidden page is on screen.
    setSelected(allLoadedSelected ? new Set() : new Set(items.map((item) => item.source_url)));
  }

  function buildQuery(): InstagramProfilePreviewRequest | null {
    const url = profileUrl.trim();
    if (!url || selectedTypes.length === 0) return null;
    return {
      profile_url: url,
      content_types: selectedTypes,
      posted_after: dateInputToRangeStart(postedAfter),
      posted_before: dateInputToRangeEnd(postedBefore),
      limit: PREVIEW_PAGE_SIZE,
    };
  }

  async function preview() {
    const query = buildQuery();
    if (!query) return;
    if (postedAfter && postedBefore && postedAfter > postedBefore) {
      setError('"Posted after" must not be later than "posted before".');
      return;
    }
    setLoading(true);
    setError(null);
    setItems([]);
    setSelected(new Set());
    setHasMore(false);
    setNextPostedBefore(null);
    resetSync();
    try {
      const result = await api.previewInstagramProfile(query);
      setItems(result.items);
      setHasMore(result.has_more);
      setNextPostedBefore(result.next_posted_before);
      setLastQuery(query);
      if (result.items.length === 0) onMessage('No items found for the selected content types.');
    } catch (caughtError) {
      // Also shown inline (not just via onMessage) since the shared message
      // banner lives at the top of the page, far from this form.
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to preview this profile.';
      setError(text);
      onMessage(text);
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (!lastQuery || !nextPostedBefore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const result = await api.previewInstagramProfile({ ...lastQuery, posted_before: nextPostedBefore });
      setItems((current) => {
        // The cursor is a date, so an item sharing a timestamp with the last
        // of the previous page comes back again -- see
        // ProfileItemPage.next_posted_before.
        const seen = new Set(current.map((item) => item.source_url));
        return [...current, ...result.items.filter((item) => !seen.has(item.source_url))];
      });
      setHasMore(result.has_more);
      setNextPostedBefore(result.next_posted_before);
      if (result.items.length === 0) onMessage('No older items found.');
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to load more items.';
      setError(text);
      onMessage(text);
    } finally {
      setLoadingMore(false);
    }
  }

  /** Resolves the chosen playlist, creating it when the user named a new
   * one. Returns null (having reported why) if there is nothing to add to. */
  async function resolveCollectionId(): Promise<string | null> {
    if (targetCollectionId) return targetCollectionId;
    const name = newCollectionName.trim();
    if (!name) {
      setError('Choose an existing playlist or name a new one first.');
      return null;
    }
    const created = await api.createCollection(name);
    setNewCollectionName('');
    return created.id;
  }

  async function addSelected() {
    const chosen = items.filter((item) => selected.has(item.source_url));
    if (chosen.length === 0) return;
    setAdding(true);
    setError(null);
    try {
      const collectionId = await resolveCollectionId();
      if (!collectionId) return;
      for (const item of chosen) {
        await api.addCollectionItem(collectionId, item);
      }
      setTargetCollectionId(collectionId);
      setSelected(new Set());
      onMessage(`Added ${chosen.length} item(s) to the playlist.`);
      await onCollectionsChanged();
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to add items to the playlist.';
      setError(text);
      onMessage(text);
    } finally {
      setAdding(false);
    }
  }

  /** Adds the first BULK_ADD_LIMIT matching items, then remembers the cursor
   * so "Add next batch" can walk the rest of the profile backward -- no manual
   * month-by-month filtering needed for a full-profile add. */
  async function addAllMatching() {
    if (!lastQuery) return;
    setAdding(true);
    setError(null);
    try {
      const collectionId = await resolveCollectionId();
      if (!collectionId) return;
      const result = await api.addProfileItemsToCollection(collectionId, { ...lastQuery, limit: BULK_ADD_LIMIT });
      setTargetCollectionId(collectionId);
      setSelected(new Set());
      setSyncCollectionId(collectionId);
      setSyncCursor(result.next_posted_before);
      setSyncHasMore(result.has_more);
      setSyncTotalAdded(result.added);
      const parts = [`Added ${result.added} item(s)`];
      if (result.already_present > 0) parts.push(`${result.already_present} already in the playlist`);
      if (result.has_more) parts.push(`more available -- click "Add next batch" to keep going`);
      onMessage(`${parts.join(' - ')}.`);
      await onCollectionsChanged();
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to add items to the playlist.';
      setError(text);
      onMessage(text);
    } finally {
      setAdding(false);
    }
  }

  /** Continues a full-profile add from where the last batch stopped, paging
   * backward one BULK_ADD_LIMIT chunk at a time. User-paced (one click per
   * chunk) so Instagram's rate limits aren't provoked by an unattended run. */
  async function addNextBatch() {
    if (!lastQuery || !syncCollectionId || !syncCursor) return;
    setAdding(true);
    setError(null);
    try {
      const result = await api.addProfileItemsToCollection(syncCollectionId, {
        ...lastQuery,
        posted_before: syncCursor,
        limit: BULK_ADD_LIMIT,
      });
      const total = syncTotalAdded + result.added;
      setSyncTotalAdded(total);
      setSyncCursor(result.next_posted_before);
      setSyncHasMore(result.has_more);
      onMessage(
        result.has_more
          ? `Added ${result.added} more (${total} total). More available — click "Add next batch" again.`
          : `Added ${result.added} more (${total} total). That's the whole profile.`,
      );
      await onCollectionsChanged();
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to add the next batch.';
      setError(text);
      onMessage(text);
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="instagram-browser">
      <div className="instagram-browser-form">
        <label>
          Instagram profile URL
          <input
            value={profileUrl}
            onChange={(event) => setProfileUrl(event.target.value)}
            placeholder="https://www.instagram.com/username/"
          />
        </label>
        <div className="instagram-content-types">
          {CONTENT_TYPES.map(({ value, label }) => (
            <label key={value} className="checkbox-chip">
              <input type="checkbox" checked={selectedTypes.includes(value)} onChange={() => toggleType(value)} />
              {label}
            </label>
          ))}
        </div>
        <div className="instagram-date-range">
          <label>
            Posted after
            <input type="date" value={postedAfter} onChange={(event) => setPostedAfter(event.target.value)} />
          </label>
          <label>
            Posted before
            <input type="date" value={postedBefore} onChange={(event) => setPostedBefore(event.target.value)} />
          </label>
          <span className="field-help">
            Only applies to posts and reels -- stories and highlights aren&apos;t date-filterable. Without a start
            date, results are capped to the most recent items so browsing an active profile stays fast.
          </span>
        </div>
        <button disabled={loading || !profileUrl.trim() || selectedTypes.length === 0} onClick={() => void preview()}>
          {loading ? 'Loading…' : 'Preview profile'}
        </button>
        {error && <div className="error">{error}</div>}
      </div>

      {items.length > 0 && (
        <>
          <div className="instagram-results-bar">
            <span>
              {items.length} item{items.length === 1 ? '' : 's'}
              {hasMore ? ' (more available)' : ''}
              {selected.size > 0 ? ` - ${selected.size} selected` : ''}
            </span>
            <button type="button" className="link-button" onClick={toggleSelectAll}>
              {allLoadedSelected ? 'Clear selection' : `Select all ${items.length}`}
            </button>
          </div>

          <div className="instagram-items-grid">
            {items.map((item) => (
              <button
                type="button"
                key={item.source_url}
                className={`instagram-item-card ${selected.has(item.source_url) ? 'selected' : ''}`}
                onClick={() => toggleSelected(item.source_url)}
              >
                {item.thumbnail_url ? (
                  <img src={item.thumbnail_url} alt="" loading="lazy" />
                ) : (
                  <div className="instagram-item-placeholder" />
                )}
                <span className="instagram-item-type">{item.content_type}</span>
                {formatPostedAt(item.posted_at) && <span className="instagram-item-date">{formatPostedAt(item.posted_at)}</span>}
                {item.caption && <span className="instagram-item-caption">{item.caption}</span>}
              </button>
            ))}
          </div>

          {hasMore && (
            <div className="instagram-load-more">
              <button type="button" className="secondary" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? 'Loading…' : 'Load older items'}
              </button>
              <span className="field-help">
                Or use “Add all matching” below to take everything without loading it here first.
              </span>
            </div>
          )}

          <div className="instagram-add-row">
            <select value={targetCollectionId} onChange={(event) => setTargetCollectionId(event.target.value)}>
              <option value="">New playlist…</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
            {!targetCollectionId && (
              <input
                value={newCollectionName}
                onChange={(event) => setNewCollectionName(event.target.value)}
                placeholder="Playlist name"
              />
            )}
            <button disabled={adding || selected.size === 0} onClick={() => void addSelected()}>
              {adding ? 'Adding…' : `Add ${selected.size || ''} to playlist`}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={adding || !lastQuery}
              onClick={() => void addAllMatching()}
              title={`Adds the first ${BULK_ADD_LIMIT} matching, then offers "Add next batch" to page the rest of the profile.`}
            >
              {adding ? 'Adding…' : 'Add all matching'}
            </button>
            {syncHasMore && syncCollectionId && (
              <button
                type="button"
                className="secondary"
                disabled={adding}
                onClick={() => void addNextBatch()}
                title="Adds the next older batch, continuing a full-profile add one chunk at a time."
              >
                {adding ? 'Adding…' : `Add next batch (+${BULK_ADD_LIMIT})`}
              </button>
            )}
          </div>
          {syncTotalAdded > 0 && (
            <div className="field-help">
              Full-profile add: {syncTotalAdded} item(s) so far{syncHasMore ? ' — more remain, keep clicking "Add next batch".' : ' — complete.'}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PlaylistsView({
  collections,
  onCollectionsChanged,
  onMessage,
  onDownloadQueued,
}: {
  collections: Collection[];
  onCollectionsChanged: () => Promise<void>;
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}) {
  if (collections.length === 0) {
    return (
      <div className="empty-state">
        <strong>No playlists yet.</strong>
        <span>Preview a profile above and add items to create one.</span>
      </div>
    );
  }

  return (
    <div className="playlists-view">
      {collections.map((collection) => (
        <PlaylistCard
          key={collection.id}
          collection={collection}
          onCollectionsChanged={onCollectionsChanged}
          onMessage={onMessage}
          onDownloadQueued={onDownloadQueued}
        />
      ))}
    </div>
  );
}

function PlaylistCard({
  collection,
  onCollectionsChanged,
  onMessage,
  onDownloadQueued,
}: {
  collection: Collection;
  onCollectionsChanged: () => Promise<void>;
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<CollectionItemState>('pending');
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<CollectionItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const total = collection.item_count;
  const downloadedCount = collection.downloaded_count;
  const pendingCount = Math.max(0, total - downloadedCount);
  const tabCount = tab === 'all' ? total : tab === 'downloaded' ? downloadedCount : pendingCount;
  const pageCount = Math.max(1, Math.ceil(tabCount / PLAYLIST_PAGE_SIZE));

  // Items an item can move between tabs (a download completing shifts it from
  // pending to downloaded), so a page that was valid can empty out. Clamp
  // back into range when the live counts shrink under the current page.
  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  // Everything the visible page depends on. It includes the live counts, so a
  // download finishing anywhere -- which moves total/downloaded on the SSE
  // snapshot -- re-fetches this page rather than leaving a stale badge. Keyed
  // on the signature rather than compared against items so it re-fetches at
  // most once per change.
  const signature = `${tab}:${page}:${total}:${downloadedCount}`;
  const loadedSignature = useRef<string | null>(null);

  const loadPage = useCallback(async () => {
    loadedSignature.current = signature;
    setLoading(true);
    setError(null);
    try {
      const fetched = await api.listCollectionItems(collection.id, {
        state: tab,
        limit: PLAYLIST_PAGE_SIZE,
        offset: page * PLAYLIST_PAGE_SIZE,
      });
      setItems(fetched);
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to load playlist items.';
      setError(text);
    } finally {
      setLoading(false);
    }
  }, [collection.id, tab, page, signature]);

  useEffect(() => {
    if (expanded && loadedSignature.current !== signature) void loadPage();
  }, [expanded, signature, loadPage]);

  function selectTab(next: CollectionItemState) {
    setTab(next);
    setPage(0);
    setSelected(new Set());
  }

  function toggleSelected(itemId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  async function downloadItems(itemIds?: string[]) {
    setBusy(true);
    setError(null);
    try {
      const jobs = await api.downloadCollection(collection.id, itemIds ? { item_ids: itemIds } : {});
      onMessage(jobs.length > 0 ? `Queued ${jobs.length} download(s).` : 'Nothing new to download in this playlist.');
      await onDownloadQueued();
      setSelected(new Set());
      // Completed state (and the Downloaded tab) fills in live as jobs finish
      // and the counts move; nothing to reload here beyond the queue itself.
    } catch (caughtError) {
      // Also shown inline (not just via onMessage) since the shared message
      // banner lives at the top of the page, far from this card.
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to queue downloads.';
      setError(text);
      onMessage(text);
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(itemId: string) {
    await api.removeCollectionItem(collection.id, itemId);
    setItems((current) => current?.filter((item) => item.id !== itemId) ?? null);
    await onCollectionsChanged();
  }

  async function deletePlaylist() {
    await api.deleteCollection(collection.id);
    await onCollectionsChanged();
  }

  return (
    <details
      className="playlist-card"
      onToggle={(event) => setExpanded((event.target as HTMLDetailsElement).open)}
    >
      <summary>
        <div>
          <h3>{collection.name}</h3>
          <span>
            {total} item(s) · {pendingCount} pending · {downloadedCount} downloaded
          </span>
        </div>
      </summary>
      <div className="playlist-expanded">
        <div className="playlist-actions">
          <button disabled={busy} onClick={() => void downloadItems()}>
            Download all
          </button>
          <button className="secondary" disabled={busy || selected.size === 0} onClick={() => void downloadItems(Array.from(selected))}>
            Download selected{selected.size ? ` (${selected.size})` : ''}
          </button>
          <button className="secondary" disabled={busy} onClick={() => void deletePlaylist()}>
            Delete playlist
          </button>
        </div>

        <div className="playlist-tabs">
          {PLAYLIST_TABS.map(({ value, label }) => {
            const count = value === 'all' ? total : value === 'downloaded' ? downloadedCount : pendingCount;
            return (
              <button
                key={value}
                type="button"
                className={`playlist-tab ${tab === value ? 'active' : ''}`}
                onClick={() => selectTab(value)}
              >
                {label} {count}
              </button>
            );
          })}
        </div>

        {error && <div className="error">{error}</div>}
        {items === null || loading ? (
          <div className="hint">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <strong>{tab === 'all' ? 'No items in this playlist.' : `No ${tab} items.`}</strong>
          </div>
        ) : (
          <>
            <div className="playlist-items">
              {items.map((item) => (
                <div key={item.id} className="playlist-item">
                  <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggleSelected(item.id)} />
                  {item.thumbnail_url ? <img src={item.thumbnail_url} alt="" loading="lazy" /> : <div className="instagram-item-placeholder" />}
                  <div className="playlist-item-meta">
                    <span>
                      {item.content_type}
                      {formatPostedAt(item.posted_at) && ` · ${formatPostedAt(item.posted_at)}`}
                    </span>
                    {item.caption && <span className="filename">{item.caption}</span>}
                    {item.downloaded_job_id && <span className="status-badge used">Downloaded</span>}
                  </div>
                  <button type="button" className="link-button" onClick={() => void removeItem(item.id)}>
                    Remove
                  </button>
                </div>
              ))}
            </div>
            {pageCount > 1 && (
              <div className="playlist-pager">
                <button type="button" className="secondary compact" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>
                  Previous
                </button>
                <span>Page {page + 1} of {pageCount}</span>
                <button type="button" className="secondary compact" disabled={page >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </details>
  );
}
