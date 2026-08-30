export type DownloadErrorCategory = 'http_401' | 'http_403' | 'http_404' | 'geo_restriction' | 'drm' | 'unsupported_url' | 'format_error' | 'ffmpeg_error' | 'network_error' | 'authentication_required' | 'rate_limited' | 'cancelled' | 'unknown';

export type DownloadStatus = 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

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
  /** Download subtitles/captions (standard yt-dlp downloads only). */
  subtitles?: boolean;
  /** Comma-separated language codes or "all"; only used when subtitles is true. */
  subtitle_langs?: string;
  /** Embed subtitles into the container instead of a sidecar file. */
  embed_subtitles?: boolean;
  /** Preferred audio-track language code (e.g. "en", "pt-BR") when a source has several. */
  audio_language?: string;
  /** What to do if the output file already exists (standard downloads). */
  conflict_strategy?: 'skip' | 'overwrite' | 'rename';
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

export interface BrowseDirectoryResponse {
  /** The chosen absolute path, or null if the user cancelled the dialog. */
  path: string | null;
}

export type InstagramContentType = 'post' | 'carousel' | 'reel' | 'story' | 'highlight';

export interface InstagramProfilePreviewRequest {
  profile_url: string;
  content_types?: InstagramContentType[];
  /** ISO datetime strings. Only applied to posts/reels -- stories/highlights
   * aren't meaningfully date-bounded, see InstaloaderService. */
  posted_after?: string;
  /** Doubles as the paging cursor -- pass the oldest posted_at you already
   * have to get the page behind it. */
  posted_before?: string;
  /** Page size. Omitted means the server default (50); a larger page costs
   * proportionally more requests to Instagram but far less than paging
   * repeatedly, since each page re-scans the ones above it. */
  limit?: number;
}

export interface ProfileItemPreview {
  source_url: string;
  content_type: InstagramContentType;
  author_username: string | null;
  /** The profile this item was discovered under. Differs from
   * author_username when Instagram credits a post to a collaborator, and it
   * is what decides the download folder. */
  profile_username: string | null;
  caption: string | null;
  thumbnail_url: string | null;
  external_id: string | null;
  posted_at: string | null;
}

export interface InstagramProfilePreviewResponse {
  items: ProfileItemPreview[];
  /** True when a content type exactly filled its page, i.e. there is more
   * behind this. */
  has_more: boolean;
  /** Pass back as `posted_before` to fetch the page behind this one. Null
   * when this is the end. */
  next_posted_before: string | null;
}

export interface CollectionAddProfileItemsResponse {
  added: number;
  already_present: number;
  has_more: boolean;
  next_posted_before: string | null;
}

export interface InstagramSessionStatus {
  configured: boolean;
  /** Set only right after a successful save, or by the explicit verify
   * call -- not populated by every status poll. */
  verified_username: string | null;
}

export interface Collection {
  id: string;
  platform: 'instagram';
  name: string;
  item_count: number;
  /** How many of item_count have completed a download. Drives the
   * Pending/Downloaded tab counts and the live "Downloaded" badge without
   * shipping every row. */
  downloaded_count: number;
  created_at: string;
  updated_at: string;
}

/** Which download-state slice of a playlist to fetch. Mirrors the server's
 * `state` query param on GET /collections/{id}/items. */
export type CollectionItemState = 'all' | 'pending' | 'downloaded';

export interface CollectionItemsQuery {
  state?: CollectionItemState;
  limit?: number;
  offset?: number;
}

export interface CollectionItem {
  id: string;
  collection_id: string;
  source_url: string;
  content_type: InstagramContentType;
  author_username: string | null;
  /** The profile this item was discovered under. Differs from
   * author_username when Instagram credits a post to a collaborator, and it
   * is what decides the download folder. */
  profile_username: string | null;
  caption: string | null;
  thumbnail_url: string | null;
  external_id: string | null;
  added_at: string;
  posted_at: string | null;
  downloaded_job_id: string | null;
}

export interface CollectionDownloadRequest {
  item_ids?: string[];
  preset?: 'best' | '1080p' | '720p' | 'audio';
  concurrent_fragments?: number;
  retries?: number;
}

export interface DownloadHistoryQuery {
  limit?: number;
  offset?: number;
}

export interface DownloadHistoryResponse {
  items: DownloadItem[];
  has_more: boolean;
}

export interface UpdateCheck {
  current: string | null;
  latest: string | null;
  update_available: boolean;
  error: string | null;
}

export interface ImportResult {
  imported_presets: number;
  imported_collections: number;
  imported_items: number;
  settings_applied: boolean;
  notes: string[];
}

export interface FolderUsage {
  name: string;
  bytes: number;
  file_count: number;
}

export interface StorageUsage {
  directory: string;
  total_bytes: number;
  free_bytes: number;
  disk_total_bytes: number;
  folders: FolderUsage[];
}

export interface DownloadPreset {
  id: string;
  name: string;
  preset: NonNullable<DownloadCreateRequest['preset']>;
  concurrent_fragments: number;
  retries: number;
  use_aria2: boolean;
  created_at: string;
}

export interface DownloadPresetCreateRequest {
  name: string;
  preset: NonNullable<DownloadCreateRequest['preset']>;
  concurrent_fragments: number;
  retries: number;
  use_aria2: boolean;
}

/** One `state` frame from GET /api/events -- everything the old 2s refresh
 * loop used to fetch from four separate endpoints. A field is null when the
 * server could not build that part, which must not blank out what the UI is
 * already showing. */
export interface ServerStateEvent {
  downloads: DownloadItem[] | null;
  status: SystemStatus | null;
  captures: CaptureItem[] | null;
  settings: SettingsResponse | null;
  /** Collection *summaries* only (counts, not items). Present so playlists
   * update live; an open playlist re-fetches its own items when these
   * counts move. Null when the server could not build this part. */
  collections: Collection[] | null;
}
