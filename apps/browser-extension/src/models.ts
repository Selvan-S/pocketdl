export type CaptureType = 'hls' | 'dash' | 'media';

export interface PendingRequest {
  url: string;
  tabId: number;
  pageUrl?: string;
  pageTitle?: string;
  headers: Record<string, string>;
  captureType: CaptureType;
  contentType?: string;
  contentLengthBytes?: number;
}

// Written by background.ts after every attempt to post a capture to the
// backend, read by popup.ts so a silently-dropped capture (backend offline,
// validation error) is still visible to the user instead of vanishing.
export interface CaptureAttemptStatus {
  ok: boolean;
  at: number;
  error?: string;
}

// Written by background.ts after a "Send to PocketDL" context-menu action,
// read by popup.ts so a failed send (backend offline, unsupported URL) is
// visible rather than silently dropped -- the standard-download counterpart
// of CaptureAttemptStatus.
export interface SendAttemptStatus {
  ok: boolean;
  at: number;
  url: string;
  error?: string;
}
