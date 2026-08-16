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
