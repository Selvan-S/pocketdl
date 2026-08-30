import type { Collection, DownloadItem, DownloadStatus } from '../types/api';

/** Snapshot of each download's status, keyed by id, so the next snapshot can
 * be diffed against it to find state transitions. */
export type StatusMap = Map<string, DownloadStatus>;

export interface FinishedDownload {
  id: string;
  status: 'completed' | 'failed';
}

export function statusMap(items: DownloadItem[]): StatusMap {
  return new Map(items.map((item) => [item.id, item.status]));
}

/** Downloads that have just crossed into a terminal state since `prev`.
 *
 * A job only counts if it was already present under a *different* status --
 * so seeding the first snapshot (every id absent from `prev`) reports
 * nothing, and a job that merely re-appears unchanged is ignored. Cancelled
 * is intentionally excluded: the user initiated it, so a notification would
 * be noise. */
export function downloadsThatFinished(prev: StatusMap, items: DownloadItem[]): FinishedDownload[] {
  const finished: FinishedDownload[] = [];
  for (const item of items) {
    const before = prev.get(item.id);
    if (before && before !== item.status && (item.status === 'completed' || item.status === 'failed')) {
      finished.push({ id: item.id, status: item.status });
    }
  }
  return finished;
}

/** A playlist is "complete" once every item it holds has been downloaded.
 * item_count === 0 is not complete (an empty playlist never finishes). */
export function collectionIsComplete(collection: Collection): boolean {
  return collection.item_count > 0 && collection.downloaded_count >= collection.item_count;
}

export function completionMap(collections: Collection[]): Map<string, boolean> {
  return new Map(collections.map((collection) => [collection.id, collectionIsComplete(collection)]));
}

/** Playlists that have just become complete since the `prev` completion map.
 * Same seeding rule as downloads: a playlist already complete in `prev` does
 * not re-notify. */
export function collectionsThatCompleted(prev: Map<string, boolean>, collections: Collection[]): Collection[] {
  return collections.filter((collection) => collectionIsComplete(collection) && !(prev.get(collection.id) ?? false));
}
