import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Collection, CollectionItem, InstagramContentType, InstagramSessionStatus, ProfileItemPreview } from '../types/api';

interface Props {
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}

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

  async function preview() {
    const url = profileUrl.trim();
    if (!url || selectedTypes.length === 0) return;
    if (postedAfter && postedBefore && postedAfter > postedBefore) {
      setError('"Posted after" must not be later than "posted before".');
      return;
    }
    setLoading(true);
    setError(null);
    setItems([]);
    setSelected(new Set());
    try {
      const result = await api.previewInstagramProfile({
        profile_url: url,
        content_types: selectedTypes,
        posted_after: dateInputToRangeStart(postedAfter),
        posted_before: dateInputToRangeEnd(postedBefore),
      });
      setItems(result.items);
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

  async function addSelected() {
    const chosen = items.filter((item) => selected.has(item.source_url));
    if (chosen.length === 0) return;
    setAdding(true);
    setError(null);
    try {
      let collectionId = targetCollectionId;
      if (!collectionId) {
        const name = newCollectionName.trim();
        if (!name) {
          setError('Choose an existing playlist or name a new one first.');
          return;
        }
        const created = await api.createCollection(name);
        collectionId = created.id;
        setNewCollectionName('');
      }
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

  async function loadItems() {
    setItems(await api.listCollectionItems(collection.id));
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
