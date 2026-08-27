import { describe, expect, it } from 'vitest';
import { extractErrorMessage } from './client';

describe('extractErrorMessage', () => {
  it('extracts a plain HTTPException detail string', () => {
    expect(extractErrorMessage('{"detail":"Collection not found"}')).toBe('Collection not found');
  });

  it('joins pydantic validation error messages', () => {
    const body = JSON.stringify({ detail: [{ msg: 'field required' }, { msg: 'invalid url' }] });
    expect(extractErrorMessage(body)).toBe('field required; invalid url');
  });

  it('falls back to the raw body for non-JSON error text', () => {
    expect(extractErrorMessage('Internal Server Error')).toBe('Internal Server Error');
  });

  it('returns null for an empty body', () => {
    expect(extractErrorMessage('')).toBeNull();
  });
});
