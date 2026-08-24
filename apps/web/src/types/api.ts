export type DownloadErrorCategory = 'http_401' | 'http_403' | 'http_404' | 'geo_restriction' | 'drm' | 'unsupported_url' | 'format_error' | 'ffmpeg_error' | 'network_error' | 'authentication_required' | 'rate_limited' | 'cancelled' | 'unknown';

export type DownloadStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface DownloadItem {
  id: string;
  url: string;
  filename: string | null;
  title: string | null;
  status: DownloadStatus;
  progress: number;
  downloaded_bytes: number;
  total_bytes: number | null;
  speed_bytes: number | null;
  eta_seconds: number | null;
  output_path: string | null;
  error: string | null;
  error_details: string | null;
  error_category: DownloadErrorCategory | null;
  exit_code: number | null;
  retry_count: number;
  impersonation: 'none' | 'auto' | 'chrome';
  referer: string | null;
  origin: string | null;
  user_agent: string | null;
  created_at: string;
  source_type: 'standard' | 'captured';
  started_at: string | null;
  finished_at: string | null;
  capture_id: string | null;
}

export interface DownloadCreateRequest {
  url: string;
  filename?: string;
  preset?: 'best' | '1080p' | '720p' | '480p' | 'audio';
  /** A specific format_id from AnalyzeResponse['formats']; overrides preset when set. */
  format_id?: string;
  concurrent_fragments?: number;
  retries?: number;
  use_aria2?: boolean;
  request_context?: {
    page_url?: string;
    referer?: string;
    origin?: string;
    user_agent?: string;
    headers?: Record<string, string>;
    impersonation?: 'none' | 'auto' | 'chrome';
  };
}

export interface SystemStatus {
  app_version: string;
  yt_dlp_version: string | null;
  ffmpeg_version: string | null;
  aria2_version: string | null;
  download_directory: string;
  active_downloads: number;
  queued_downloads: number;
}


export interface AnalyzedFormat {
  format_id: string;
  ext: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  vcodec: string | null;
  acodec: string | null;
  filesize: number | null;
  tbr: number | null;
  protocol: string | null;
}

export interface AnalyzeResponse {
  source_url: string;
  webpage_url: string | null;
  title: string | null;
  uploader: string | null;
  duration_seconds: number | null;
  thumbnail: string | null;
  extractor: string | null;
  is_live: boolean | null;
  formats: AnalyzedFormat[];
}

export interface CaptureVariant {
  index: number;
  url: string;
  quality_label: string;
  bandwidth_bps: number | null;
  width: number | null;
  height: number | null;
  codecs: string | null;
  frame_rate: number | null;
  name: string | null;
  has_separate_audio: boolean;
  /** Bitrate x duration. An HLS stream's exact size is unknowable before
   * downloading, so this must always be presented as an estimate. */
  estimated_size_bytes: number | null;
}

export interface CaptureItem {
  id: string;
  media_url: string;
  page_url: string | null;
  page_title: string | null;
  referer: string | null;
  origin: string | null;
  user_agent: string | null;
  headers: Record<string, string>;
  capture_type: 'hls' | 'dash' | 'media';
  content_type: string | null;
  size_bytes: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  metadata_status: 'pending' | 'ready' | 'failed';
  metadata_error: string | null;
  looks_suspicious: boolean;
  status: 'captured' | 'used';
  created_at: string;
  used_at: string | null;
  variants_status: 'pending' | 'ready' | 'failed' | 'none';
  variants: CaptureVariant[];
}

export interface CaptureDownloadRequest {
  filename?: string;
  preset?: 'best' | '1080p' | '720p' | 'audio';
  concurrent_fragments?: number;
  retries?: number;
  /** Position in the capture's own variant list. Omitted downloads the
   * master, leaving the quality choice to the player's default. */
  variant_index?: number;
}

export interface SettingsResponse {
  download_directory: string;
  default_download_directory: string;
}
