import { describe, expect, it } from 'vitest';
import type { Collection, DownloadItem } from '../types/api';
import {
  collectionIsComplete,
  collectionsThatCompleted,
  completionMap,
  downloadsThatFinished,
  statusMap,
} from './notifications';

function download(id: string, status: DownloadItem['status']): DownloadItem {
  return {
    id, url: `https://example.com/${id}`, filename: null, title: null, status,
    progress: 0, downloaded_bytes: 0, total_bytes: null, speed_bytes: null, eta_seconds: null,
    output_path: null, error: null, error_details: null, error_category: null, exit_code: null,
    retry_count: 0, impersonation: 'auto', referer: null, origin: null, user_agent: null,
    created_at: '', source_type: 'standard', started_at: null, finished_at: null, capture_id: null,
  };
}

function collection(id: string, item_count: number, downloaded_count: number): Collection {
  return { id, platform: 'instagram', name: `pl-${id}`, item_count, downloaded_count, created_at: '', updated_at: '' };
}

describe('downloadsThatFinished', () => {
  it('reports a job that transitioned running -> completed', () => {
    const prev = statusMap([download('a', 'running')]);
    expect(downloadsThatFinished(prev, [download('a', 'completed')])).toEqual([{ id: 'a', status: 'completed' }]);
  });

  it('reports a failure transition', () => {
    const prev = statusMap([download('a', 'running')]);
    expect(downloadsThatFinished(prev, [download('a', 'failed')])).toEqual([{ id: 'a', status: 'failed' }]);
  });

  it('ignores a job absent from the previous snapshot (seeding)', () => {
    expect(downloadsThatFinished(new Map(), [download('a', 'completed')])).toEqual([]);
  });

  it('ignores an unchanged completed job', () => {
    const prev = statusMap([download('a', 'completed')]);
    expect(downloadsThatFinished(prev, [download('a', 'completed')])).toEqual([]);
  });

  it('ignores a cancellation', () => {
    const prev = statusMap([download('a', 'running')]);
    expect(downloadsThatFinished(prev, [download('a', 'cancelled')])).toEqual([]);
  });
});

describe('collection completion', () => {
  it('is complete only when every item is downloaded', () => {
    expect(collectionIsComplete(collection('a', 3, 3))).toBe(true);
    expect(collectionIsComplete(collection('a', 3, 2))).toBe(false);
    expect(collectionIsComplete(collection('a', 0, 0))).toBe(false);
  });

  it('reports a playlist that just became complete', () => {
    const prev = completionMap([collection('a', 3, 2)]);
    expect(collectionsThatCompleted(prev, [collection('a', 3, 3)]).map((c) => c.id)).toEqual(['a']);
  });

  it('does not re-notify an already-complete playlist', () => {
    const prev = completionMap([collection('a', 3, 3)]);
    expect(collectionsThatCompleted(prev, [collection('a', 3, 3)])).toEqual([]);
  });
});
