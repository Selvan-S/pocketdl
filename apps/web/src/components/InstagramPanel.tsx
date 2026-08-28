import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  Collection,
  CollectionItem,
  InstagramContentType,
  InstagramProfilePreviewRequest,
  InstagramSessionStatus,
  ProfileItemPreview,
} from '../types/api';

interface Props {
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}

// Ceiling for "Add all matching". The server clamps to this too; it is
// stated here so the UI can say what it stopped at rather than silently
// adding a subset. Sized so one request still fits the backend's budget --
// see _MAX_PAGE_SIZE in instaloader_service.py.
const BULK_ADD_LIMIT = 200;

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

export function InstagramPanel({ onMessage, onDownloadQueued }: Props) {
  const [session, setSession] = useState<InstagramSessionStatus | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);

  const refreshCollections = useCallback(async () => {
    try {
      setCollections(await api.listCollections());
    } catch {
      // The Instagram panel is best-effort supplementary UI; a failed
      // refresh here should not disturb the rest of the app.
    }
  }, []);

  useEffect(() => {
    api.instagramSessionStatus().then(setSession).catch(() => undefined);
    void refreshCollections();
  }, [refreshCollections]);

  return (
    <div className="instagram-panel">
      <SessionControl session={session} onChange={setSession} onMessage={onMessage} />
      <ProfileBrowser collections={collections} onCollectionsChanged={refreshCollections} onMessage={onMessage} />
      <PlaylistsView
        collections={collections}
        onCollectionsChanged={refreshCollections}
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

  /** Adds everything the current query matches, without loading it all into
   * the page first -- the point of the feature: a profile with 128 reels
   * should not need three manual pages and 128 cards on screen to select. */
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
      const parts = [`Added ${result.added} item(s)`];
      if (result.already_present > 0) parts.push(`${result.already_present} already in the playlist`);
      if (result.has_more) parts.push(`stopped at ${BULK_ADD_LIMIT} -- narrow the date range for the rest`);
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
              title={`Adds everything matching the current filters, up to ${BULK_ADD_LIMIT}, without loading it all here.`}
            >
              {adding ? 'Adding…' : 'Add all matching'}
            </button>
          </div>
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
  const [items, setItems] = useState<CollectionItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The count this card's item list was last fetched for. Keyed on the count
  // rather than compared against items.length so a single change triggers at
  // most one re-fetch: if the two ever disagreed persistently, comparing
  // lengths would re-fetch on every render forever.
  const loadedForCount = useRef<number | null>(null);

  const loadItems = useCallback(async () => {
    loadedForCount.current = collection.item_count;
    setItems(await api.listCollectionItems(collection.id));
  }, [collection.id, collection.item_count]);

  // The list used to be fetched once, on first expand, and cached forever --
  // so adding items to an already-open playlist updated the header count
  // while the list underneath still showed the old contents, leaving no way
  // to see what "Download all" would act on.
  useEffect(() => {
    if (items !== null && loadedForCount.current !== collection.item_count) {
      void loadItems();
    }
  }, [collection.item_count, items, loadItems]);

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
      setItems(await api.listCollectionItems(collection.id));
      setSelected(new Set());
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
      onToggle={(event) => {
        if ((event.target as HTMLDetailsElement).open && items === null) void loadItems();
      }}
    >
      <summary>
        <div>
          <h3>{collection.name}</h3>
          <span>{collection.item_count} item(s)</span>
        </div>
      </summary>
      <div className="playlist-expanded">
        <div className="playlist-actions">
          <button disabled={busy} onClick={() => void downloadItems()}>
            Download all
          </button>
          <button className="secondary" disabled={busy || selected.size === 0} onClick={() => void downloadItems(Array.from(selected))}>
            Download selected
          </button>
          <button className="secondary" disabled={busy} onClick={() => void deletePlaylist()}>
            Delete playlist
          </button>
        </div>
        {error && <div className="error">{error}</div>}
        {items === null ? (
          <div className="hint">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <strong>No items in this playlist.</strong>
          </div>
        ) : (
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
        )}
      </div>
    </details>
  );
}
