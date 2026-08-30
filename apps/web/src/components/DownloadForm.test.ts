import { describe, expect, it } from 'vitest';
import { parseUrls } from './DownloadForm';

describe('parseUrls', () => {
  it('returns a single URL as one entry', () => {
    expect(parseUrls('https://example.com/a')).toEqual(['https://example.com/a']);
  });

  it('splits multiple lines into a batch', () => {
    expect(parseUrls('https://example.com/a\nhttps://example.com/b')).toEqual([
      'https://example.com/a',
      'https://example.com/b',
    ]);
  });

  it('trims whitespace and drops blank lines', () => {
    expect(parseUrls('  https://example.com/a  \n\n   \nhttps://example.com/b')).toEqual([
      'https://example.com/a',
      'https://example.com/b',
    ]);
  });

  it('de-duplicates repeated URLs', () => {
    expect(parseUrls('https://example.com/a\nhttps://example.com/a')).toEqual(['https://example.com/a']);
  });

  it('returns an empty list for empty or whitespace-only input', () => {
    expect(parseUrls('   \n  ')).toEqual([]);
  });
});
