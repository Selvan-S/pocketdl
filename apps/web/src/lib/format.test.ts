import { describe, expect, it } from 'vitest';
import { clampProgress } from './format';

describe('clampProgress', () => {
  it('clamps values below zero', () => expect(clampProgress(-1)).toBe(0));
  it('clamps values above 100', () => expect(clampProgress(101)).toBe(100));
  it('preserves values in range', () => expect(clampProgress(42)).toBe(42));
});
