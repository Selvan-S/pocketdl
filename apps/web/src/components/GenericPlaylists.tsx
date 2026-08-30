import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { Collection, CollectionItem } from '../types/api';

interface Props {
  // Generic (non-Instagram) collections only. App filters by platform so each
  // tab manages its own playlists.
  collections: Collection[];
  onCollectionsChanged: () => Promise<void>;
  onMessage: (message: string) => void;
  onDownloadQueued: () => Promise<void>;
}

/** Playlists of plain URLs for normal downloads. Each downloads via yt-dlp
 * into its own folder (<download dir>/Web/<playlist name>/). */
export function GenericPlaylists({ collections, onCollectionsChanged, onMessage, onDownloadQueued }: Props) {
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);

  async function createPlaylist() {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    try {
      await api.createCollection(name, 'generic');
      setNewName('');
      await onCollectionsChanged();
      onMessage(`Created playlist “${name}”.`);
    } catch (error) {
      onMessage(error instanceof Error ? error.message : 'Unable to create playlist.');
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <div className="eyebrow">PLAYLISTS</div>
          <h2>Saved URL playlists</h2>
          <span>Save a set of URLs and download them together into their own folder.</span>
        </div>
      </div>
      <div className="generic-create-row">
        <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New playlist name" maxLength={200} />
        <button disabled={creating || !newName.trim()} onClick={() => void createPlaylist()}>
          {creating ? 'Creating…' : 'Create playlist'}
        </button>
      </div>
      {collections.length === 0 ? (
        <div className="empty-state">
          <strong>No playlists yet.</strong>
          <span>Create one above, then add URLs to it.</span>
        </div>
      ) : (
        <div className="playlists-view">
          {collections.map((collection) => (
            <GenericPlaylistCard
              key={collection.id}
              collection={collection}
              onCollectionsChanged={onCollectionsChanged}
              onMessage={onMessage}
              onDownloadQueued={onDownloadQueued}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function GenericPlaylistCard({
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
  const [urls, setUrls] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedForCount = useRef<number | null>(null);

  const load = useCallback(async () => {
    loadedForCount.current = collection.item_count;
    try {
      setItems(await api.listCollectionItems(collection.id, { state: 'all', limit: 200 }));
    } catch {
      // Non-critical.
    }
  }, [collection.id, collection.item_count]);

  // Re-fetch when the live count changes (a download finished, or URLs added).
  useEffect(() => {
    if (items !== null && loadedForCount.current !== collection.item_count) void load();
  }, [collection.item_count, items, load]);

  async function addUrls() {
    const lines = Array.from(new Set(urls.split('\n').map((line) => line.trim()).filter(Boolean)));
    if (lines.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.addUrlsToCollection(collection.id, lines);
      setUrls('');
      onMessage(`Added ${result.added} URL(s)${result.already_present ? `, ${result.already_present} already present` : ''}.`);
      await onCollectionsChanged();
      await load();
    } catch (caughtError) {
      const text = caughtError instanceof Error ? caughtError.message : 'Unable to add URLs.';
      setError(text);
      onMessage(text);
    } finally {
      setBusy(false);
    }
  }

  async function downloadAll() {
    setBusy(true);
    setError(null);
    try {
      const jobs = await api.downloadCollection(collection.id, {});
      onMessage(jobs.length > 0 ? `Queued ${jobs.length} download(s).` : 'Nothing new to download in this playlist.');
      await onDownloadQueued();
      await load();
    } catch (caughtError) {
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
    <details className="playlist-card" onToggle={(event) => { if ((event.target as HTMLDetailsElement).open && items === null) void load(); }}>
      <summary>
        <div>
          <h3>{collection.name}</h3>
          <span>{collection.item_count} item(s) · {collection.downloaded_count} downloaded</span>
        </div>
      </summary>
      <div className="playlist-expanded">
        <label htmlFor={`urls-${collection.id}`}>Add URLs <span className="hint">(one per line)</span></label>
        <textarea
          id={`urls-${collection.id}`}
          value={urls}
          onChange={(event) => setUrls(event.target.value)}
          placeholder="https://example.com/one&#10;https://example.com/two"
          autoCapitalize="none"
          autoCorrect="off"
        />
        <div className="playlist-actions">
          <button className="secondary" disabled={busy || !urls.trim()} onClick={() => void addUrls()}>Add URLs</button>
          <button disabled={busy} onClick={() => void downloadAll()}>Download all</button>
          <button className="secondary" disabled={busy} onClick={() => void deletePlaylist()}>Delete playlist</button>
        </div>
        {error && <div className="error">{error}</div>}
        {items === null ? (
          <div className="hint">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty-state"><strong>No URLs yet.</strong></div>
        ) : (
          <div className="playlist-items">
            {items.map((item) => (
              <div key={item.id} className="playlist-item">
                <div className="playlist-item-meta">
                  <span className="filename">{item.source_url}</span>
                  {item.downloaded_job_id && <span className="status-badge used">Downloaded</span>}
                </div>
                <button type="button" className="link-button" onClick={() => void removeItem(item.id)}>Remove</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
