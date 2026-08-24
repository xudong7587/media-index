export type MediaItem = {
  id: number;
  tmdb_id: number;
  media_type: "movie" | "tv" | "variety";
  category?: "movie" | "tv" | "variety" | "concert" | "documentary" | "anime";
  title: string;
  year?: string;
  release_date?: string;
  poster_url?: string;
  backdrop_url?: string;
  overview?: string;
  vote_average?: number;
  status?: string;
  genres?: string[];
  runtime?: number;
  seasons?: { season_number: number; name: string; episode_count: number; air_date?: string }[];
};

export type TrackingTask = {
  id: number;
  tmdb_id: number;
  media_type: string;
  category?: MediaItem["category"];
  title: string;
  year: string;
  poster_url?: string;
  overview?: string;
  season_number: number;
  save_target: string;
  save_path: string;
  status: string;
  last_error?: string;
  last_checked_at?: string;
  next_check_at?: string;
  decision_state?: string;
  saved_count?: number;
  triggered_count?: number;
  episode_count?: number;
  last_saved_episode?: number;
  last_storage_check_at?: string;
  storage_check_message?: string;
  check_time: string;
  provider?: "qas" | "quark" | "p115" | "";
  provider_states: TrackingProviderState[];
};

export type TrackingProviderState = {
  id: number;
  provider: "qas" | "quark" | "p115";
  save_path: string;
  status: string;
  decision_state?: string;
  saved_count: number;
  triggered_count: number;
  episode_count: number;
  last_saved_episode?: number;
  last_storage_check_at?: string;
  storage_check_message?: string;
  storage_syncing?: boolean;
  last_error?: string;
  active_job?: {
    id: number;
    status: string;
    stage: string;
    message: string;
  } | null;
};

export type WishlistItem = {
  id: number;
  tmdb_id: number;
  media_type: string;
  category?: MediaItem["category"];
  title: string;
  year: string;
  poster_url?: string;
  overview?: string;
  status: string;
  created_at: string;
  season_number?: number;
  save_target?: "cloud" | "local";
  check_hour: number;
  tmdb_date?: string;
  next_check_at?: string;
  last_checked_at?: string;
  last_error?: string;
  retry_count?: number;
  provider?: "qas" | "quark" | "p115" | "";
  provider_states: WishlistProviderState[];
};

export type WishlistProviderState = {
  id: number;
  provider: "qas" | "quark" | "p115";
  status: string;
  next_check_at?: string;
  last_checked_at?: string;
  last_error?: string;
};

export type ReviewCandidate = {
  id: number;
  job_id: number;
  tmdb_id?: number;
  media_type?: string;
  season_number?: number;
  share_url: string;
  source_title: string;
  search_query: string;
  source: string;
  cloud_type: "quark" | "115" | "";
  provider: "qas" | "quark" | "p115" | "moviepilot_115" | "";
  job_provider?: "qas" | "quark" | "p115" | "moviepilot_115" | "";
  published_at: string;
  score: number;
  rejected: number;
  reasons: string[];
  job_message?: string;
  review_state?: string;
  files: string[];
};

export type TransferJob = {
  id: number;
  status: "running" | "ready" | "retry_wait" | "done" | "triggered" | "needs_review" | "failed" | "stopped";
  stage: string;
  message: string;
  save_path: string;
  provider?: "qas" | "quark" | "p115" | "moviepilot_115" | "openlist" | "strm" | "";
  target?: "cloud" | "local" | "";
  display_title?: string;
  media_type?: string;
  season_number?: number;
  source_file?: string;
  renamed_file?: string;
  created_at?: string;
  finished_at?: string;
};

export type EmbyDashboard = {
  server: { name: string; version: string; operating_system: string };
  counts: { MovieCount?: number; SeriesCount?: number; EpisodeCount?: number; SongCount?: number };
  libraries: Array<{ id: string; name: string; collection_type: string; cover_item_id: string }>;
  sessions: Array<{ id: string; user_name: string; device_name: string; item_name: string; item_id: string; is_playing: boolean }>;
  latest_items: Array<{ id: string; name: string; type: string; year?: number; rating?: number; has_image?: boolean }>;
};

export type OpenListCopyTask = {
  id: string;
  name: string;
  state: "running" | "done" | "failed";
  status: string;
  progress: number;
  total_bytes: number;
  error: string;
  start_time?: string;
  end_time?: string;
};

export type WecomTransferRecord = {
  id: number;
  display_title: string;
  media_type: string;
  provider: "qas" | "quark" | "p115" | "moviepilot_115" | "openlist" | "";
  status: string;
  stage: string;
  message: string;
  save_path: string;
  request_source?: "wecom" | "telegram" | "";
  request_user: string;
  created_at: string;
  finished_at?: string;
};

export type TransferBatch = {
  id: number;
  status: "running" | "done" | "partial" | "needs_review" | "failed" | "stopped";
  message: string;
  providers: ("qas" | "quark" | "p115")[];
  seasons: number[];
  children: TransferJob[];
};

export type ConfigStatus = {
  has_tmdb_key: boolean;
  has_qas: boolean;
  has_moviepilot_115: boolean;
  moviepilot_base_url: string;
  has_moviepilot_token: boolean;
  moviepilot_115_plugin_id: string;
  has_p115_cookie: boolean;
  has_quark_cookie: boolean;
  quark_root_path: string;
  quark_staging_path: string;
  p115_auth_mode: "cookie" | "open";
  has_p115_open: boolean;
  p115_root_path: string;
  p115_staging_path: string;
  p115_local_path: string;
  p115_strm_source_root: string;
  quark_strm_source_root: string;
  enabled_providers: ("qas" | "quark" | "p115" | "moviepilot_115")[];
  default_provider: "qas" | "quark" | "p115" | "moviepilot_115";
  has_pansou: boolean;
  has_proxy: boolean;
  qas_base_url: string;
  pansou_url: string;
  proxy_url: string;
  cloud_root: string;
  qas_root: string;
  local_root: string;
  category_paths: Record<string, string>;
  qas_category_paths: Record<string, string>;
  p115_category_paths: Record<string, string>;
  quark_category_paths: Record<string, string>;
  strm_output_root: string;
  strm_playback_base_url: string;
  strm_library_root_id: string;
  p115_strm_enabled: boolean;
  p115_strm_incremental_cron: string;
  p115_strm_scrape_enabled: boolean;
  quark_strm_enabled: boolean;
  quark_strm_incremental_cron: string;
  quark_strm_scrape_enabled: boolean;
  strm_video_extensions: string[];
  strm_excluded_name_tokens: string[];
  strm_min_file_size_mb: number;
  emby_base_url: string;
  has_emby_api_key: boolean;
  emby_proxy_port: number;
  has_emby_deletion_webhook_token: boolean;
  emby_strm_library_root: string;
  emby_deletion_auto_confirm: boolean;
  emby_deletion_mode: "trash";
  emby_library_refresh_enabled: boolean;
  emby_library_id: string;
  emby_cover_refresh_enabled: boolean;
  emby_cover_refresh_hours: number;
  emby_cover_style: "collage" | "showcase" | "mosaic" | "minimal";
  media_folder_naming_rule: string;
  season_folder_naming_rule: string;
  movie_naming_rule: string;
  episode_naming_rule: string;
  quality_priority_keywords: string[];
  season_subdirectory_enabled: boolean;
  openlist_enabled: boolean;
  openlist_auto_sync: boolean;
  openlist_auto_sync_direction: "bidirectional" | "qas_to_p115" | "p115_to_qas";
  openlist_url: string;
  has_openlist_token: boolean;
  openlist_qas_library_path: string;
  openlist_p115_library_path: string;
  wishlist_default_check_hour: number;
  wishlist_scheduler_enabled: boolean;
  wishlist_poll_minutes: number;
  tracking_scheduler_enabled: boolean;
  tracking_poll_minutes: number;
  tracking_check_time: string;
  tracking_retry_interval_minutes: number;
  tracking_max_retries: number;
  notification_external_enabled: boolean;
  public_base_url: string;
  wecom_callback_url: string;
  telegram_enabled: boolean;
  telegram_channel_source_enabled: boolean;
  has_telegram_token: boolean;
  telegram_chat_id: string;
  telegram_api_host: string;
  wecom_enabled: boolean;
  has_wecom_key: boolean;
  wecom_origin: string;
  wecom_app_enabled: boolean;
  wecom_corp_id: string;
  has_wecom_app_secret: boolean;
  wecom_app_agent_id: number;
  wecom_app_to_user: string;
  wecom_app_to_party: string;
  wecom_app_to_tag: string;
  wecom_callback_enabled: boolean;
  has_wecom_callback_token: boolean;
  has_wecom_callback_aes_key: boolean;
  wecom_callback_allowed_users: string;
  direct_download_enabled: boolean;
  interaction_providers: ("qas" | "p115")[];
  direct_download_provider: "qas" | "p115";
  direct_download_save_path: string;
  version: string;
};

export type Genre = {
  id: number;
  name: string;
};

export type ResourceStatus = {
  ok: boolean;
  found: boolean;
  ready?: boolean;
  requires_review?: boolean;
  candidate_count?: number;
  candidates?: ResourceCandidateOption[];
  stage?: string;
  message: string;
  title?: string;
  share_url?: string;
  source_share_url?: string;
  file_count?: number;
  episode_numbers?: number[];
  cached?: boolean;
  cloud_types?: ("quark" | "115")[];
  provider?: "qas" | "quark" | "p115";
};

export type ResourceCandidateOption = {
  share_url: string;
  title?: string;
  source?: string;
  published_at?: string;
  query?: string;
  score?: number;
  reasons?: string[];
  files?: string[];
  cloud_type?: "quark" | "115" | string;
  provider?: "qas" | "quark" | "p115" | string;
};

export type NotificationItem = {
  id: number;
  type: "info" | "success" | "warning" | "error";
  title: string;
  message: string;
  action_page: string;
  poster_url: string;
  is_read: number;
  created_at: string;
};

export type NotificationFeed = {
  items: NotificationItem[];
  unread_count: number;
};


export type OpenListEntry = {
  name: string;
  is_dir: boolean;
  size?: number;
  modified?: string;
};

export type MediaWorkflow = {
  job_id: number | null;
  status: string;
  stage?: string;
  message: string;
  steps: Array<{
    key: string;
    label: string;
    status: "pending" | "running" | "done" | "failed" | "review" | "skipped";
    message: string;
    updated_at?: string;
  }>;
};

export type QuarkDirectoryEntry = {
  file_id: string;
  parent_id: string;
  name: string;
  size: number;
  is_dir: boolean;
  sha1_available: boolean;
};

export type P115DirectoryEntry = {
  file_id: string;
  parent_id: string;
  name: string;
  size: number;
  is_dir: boolean;
};

export type CrossCloudTransfer = {
  id: number;
  source_provider: "quark";
  source_parent_id: string;
  source_file_id: string;
  source_name: string;
  source_size: number;
  source_sha1: string;
  target_provider: "p115";
  target_parent_path: string;
  target_parent_id: string;
  target_name: string;
  target_file_id: string;
  strategy: "rapid_then_stream" | "provider_sha1_rapid_then_stream" | "stream_hash_then_probe";
  state: string;
  stage_message: string;
  attempt: number;
  rapid_probe_result: "" | "hit" | "miss";
  fingerprinted_bytes: number;
  uploaded_bytes: number;
  total_bytes: number;
  cleanup_state: string;
  last_error_message_safe: string;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

export type CrossCloudTransferEvent = {
  id: number;
  attempt: number;
  state: string;
  message: string;
  fingerprinted_bytes: number;
  uploaded_bytes: number;
  created_at: string;
};

export type MediaAsset = {
  id: number;
  provider: "p115" | "quark";
  file_id: string;
  parent_id: string;
  name: string;
  size: number;
  sha1: string;
  media_type: string;
  tmdb_id?: number | null;
  source_transfer_id?: number | null;
  status: "discovered" | "ready" | "needs_review" | "deleted" | "unavailable";
  last_seen_at: string;
};

export type StrmEntry = {
  id: number;
  asset_id: number;
  relative_path: string;
  status: string;
  last_error_safe: string;
  last_written_at?: string | null;
  asset_name: string;
  asset_status: string;
  provider?: "p115" | "quark";
};

export type DeletionIntent = {
  id: number;
  asset_id: number;
  asset_name: string;
  file_id: string;
  state: string;
  trigger_source: string;
  message_safe: string;
  requested_at: string;
};

export type ChannelSubscription = {
  id: number;
  channel_id: string;
  display_name: string;
  enabled: boolean;
  auto_transfer: boolean;
  require_douban_match: boolean;
  douban_titles: string[];
  last_checked_at?: string | null;
  last_resource_at?: string | null;
  last_error?: string;
};

export type ChannelMessage = {
  id: number;
  display_name: string;
  channel_id: string;
  message_id: number;
  text_preview: string;
  link_count: number;
  state: string;
  message_safe: string;
  transfer_job_id?: number | null;
  created_at: string;
  indexed_resource_count: number;
};

export type PansouChannelCandidate = {
  raw_value: string;
  channel_id: string;
  display_name: string;
  status: "importable" | "existing" | "unrecognized";
  reason: string;
  evidence_field: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: unknown; message?: unknown };
      const detail = payload.detail ?? payload.message;
      if (typeof detail === "string" && detail.trim()) message = detail.trim();
    } catch {
      // Keep the HTTP status when the server did not return JSON.
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export const api = {
  me: () => request<{ ok: boolean; user: string }>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<{ ok: boolean; user: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  config: () => request<ConfigStatus>("/api/config/status"),
  configSecret: (name: string) => request<{ name: string; value: string }>(`/api/config/secret/${encodeURIComponent(name)}`, { cache: "no-store" }),
  exportConfig: () => request<{ format: string; exported_at: string; settings: Record<string, string>; task_data: { wishlist: Record<string, unknown>[]; tracking: Record<string, unknown>[] } }>("/api/config/export"),
  importConfig: (payload: { format: string; settings: Record<string, string>; task_data?: { wishlist: Record<string, unknown>[]; tracking: Record<string, unknown>[] } }) =>
    request<{ ok: boolean; message: string }>("/api/config/import", { method: "POST", body: JSON.stringify(payload) }),
  testPansou: () =>
    request<{ ok: boolean; message: string; error?: string; result_count?: number }>("/api/config/test-pansou", { method: "POST" }),
  testTmdb: () =>
    request<{ ok: boolean; message: string; genre_count?: number }>("/api/config/test-tmdb", { method: "POST" }),
  testQas: () => request<{ ok: boolean; message: string }>("/api/config/test-qas", { method: "POST" }),
  testMoviePilot115: () =>
    request<{
      ok: boolean;
      message: string;
      connected?: boolean;
      plugin_available?: boolean;
      plugin_enabled?: boolean;
      client_ready?: boolean;
      plugin_running?: boolean;
      capabilities?: string[];
    }>("/api/config/test-moviepilot-115", { method: "POST" }),
  importP115FromOpenList: () =>
    request<{ ok: boolean; message: string; mode?: "cookie" | "open"; mount_path?: string }>("/api/config/import-p115-from-openlist", {
      method: "POST",
    }),
  clearP115Open: () =>
    request<{ ok: boolean; message: string; has_p115_cookie: boolean; has_p115_open: boolean }>("/api/config/clear-p115-open", {
      method: "POST",
    }),
  testP115: () =>
    request<{ ok: boolean; message: string; root_item_count?: number; native_ok?: boolean; relogin_required?: boolean }>("/api/config/test-p115", { method: "POST" }),
  testQuark: () =>
    request<{ ok: boolean; message: string; root_item_count?: number; account?: { user_id: string; nickname: string } }>("/api/config/test-quark", { method: "POST" }),
  startQuarkQrLogin: () =>
    request<{ ok: boolean; message?: string; session_id?: string; qr_url?: string; expires_in_seconds?: number }>("/api/config/quark/qr/start", { method: "POST" }),
  pollQuarkQrLogin: (sessionId: string) =>
    request<{ ok: boolean; status: "waiting" | "success" | "expired" | "failed"; message: string }>("/api/config/quark/qr/poll", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
  startP115OpenQrLogin: () =>
    request<{ ok: boolean; message?: string; session_id?: string; qr_url?: string; expires_in_seconds?: number }>("/api/config/p115/open/qr/start", { method: "POST" }),
  pollP115OpenQrLogin: (sessionId: string) =>
    request<{ ok: boolean; status: "waiting" | "scanned" | "success" | "expired" | "failed"; message: string }>("/api/config/p115/open/qr/poll", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
  inspectQuarkShare: (shareUrl: string) =>
    request<{
      ok: boolean;
      message: string;
      title?: string;
      file_count?: number;
      directory_count?: number;
      video_count?: number;
      truncated?: boolean;
      files?: { name: string; size: number; is_dir: boolean; is_video: boolean }[];
    }>("/api/config/quark/share/inspect", {
      method: "POST",
      body: JSON.stringify({ share_url: shareUrl }),
    }),
  cloudWorkspace: () =>
    request<{
      quark_connected: boolean;
      p115_connected: boolean;
      default_p115_target_path: string;
      stream_buffer_bytes: number;
      upload_part_bytes: number;
    }>("/api/cloud/workspace"),
  listQuarkDirectory: (parentId = "0") =>
    request<QuarkDirectoryEntry[]>(`/api/cloud/quark/directory?parent_id=${encodeURIComponent(parentId)}`),
  listP115Directory: (parentId = "0") =>
    request<{ parent_id: string; entries: P115DirectoryEntry[] }>(`/api/cloud/p115/directory?parent_id=${encodeURIComponent(parentId)}`),
  crossCloudTransfers: () => request<CrossCloudTransfer[]>("/api/cloud/cross-transfers"),
  crossCloudTransferEvents: (id: number) => request<CrossCloudTransferEvent[]>(`/api/cloud/cross-transfers/${id}/events`),
  createCrossCloudTransfer: (payload: { source_parent_id: string; source_file_id: string; target_parent_path: string; target_name?: string }) =>
    request<CrossCloudTransfer>("/api/cloud/cross-transfers", { method: "POST", body: JSON.stringify(payload) }),
  runCrossCloudTransfer: (id: number) =>
    request<{ ok: boolean; transfer_id: number; state: string }>(`/api/cloud/cross-transfers/${id}/run`, { method: "POST" }),
  cancelCrossCloudTransfer: (id: number) => request<CrossCloudTransfer>(`/api/cloud/cross-transfers/${id}/cancel`, { method: "POST" }),
  deleteCrossCloudTransfer: (id: number) => request<void>(`/api/cloud/cross-transfers/${id}`, { method: "DELETE" }),
  mediaAssets: () => request<MediaAsset[]>("/api/cloud/assets"),
  scanP115Inventory: (rootPath: string, maxFiles = 10000) => request<{ provider: string; root_path: string; directories_scanned: number; files_indexed: number; truncated: boolean; auto_strm?: { ok: boolean; created?: number; replaced?: number; unchanged?: number; scraped?: number; message?: string } | null }>("/api/cloud/inventory/p115", {
    method: "POST", body: JSON.stringify({ root_path: rootPath, max_files: maxFiles }),
  }),
  scanQuarkInventory: (rootPath: string, maxFiles = 10000) => request<{ provider: string; root_path: string; directories_scanned: number; files_indexed: number; truncated: boolean; auto_strm?: { ok: boolean; created?: number; replaced?: number; unchanged?: number; scraped?: number; message?: string } | null }>("/api/cloud/inventory/quark", {
    method: "POST", body: JSON.stringify({ root_path: rootPath, max_files: maxFiles }),
  }),
  strmEntries: () => request<StrmEntry[]>("/api/cloud/strm"),
  reconcileStrm: (payload: { output_root?: string; playback_base_url?: string; provider?: "p115" | "quark" }) => request<{ created: number; replaced: number; unchanged: number; filtered: number; conflicts: number; removed: number; scraped: number }>("/api/cloud/strm/reconcile", {
    method: "POST", body: JSON.stringify(payload),
  }),
  startStrmJob: (payload: { provider: "p115" | "quark"; mode: "incremental" | "full"; root_path: string; output_root: string; playback_base_url?: string }) => request<{ ok: boolean; job_id: number; message: string }>("/api/cloud/strm/jobs", {
    method: "POST", body: JSON.stringify(payload),
  }),
  deletionIntents: () => request<DeletionIntent[]>("/api/cloud/deletion-intents"),
  testEmby: () => request<{ ok: boolean; message: string; server_name?: string; version?: string }>("/api/integrations/emby/test", { method: "POST" }),
  embyDashboard: () => request<EmbyDashboard>("/api/integrations/emby/dashboard"),
  applyEmbyLibraryCover: (libraryId: string, payload: { title: string; style: "collage" | "showcase" | "mosaic" | "minimal" }) =>
    request<{ ok: boolean; message: string }>(`/api/integrations/emby/libraries/${encodeURIComponent(libraryId)}/cover`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  refreshEmbyLibraryCovers: (style: "collage" | "showcase" | "mosaic" | "minimal") =>
    request<{ ok: boolean; message: string; updated: number; failed: number }>("/api/integrations/emby/libraries/covers/refresh", {
      method: "POST", body: JSON.stringify({ title: "", style }),
    }),
  createDeletionIntent: (assetId: number) => request<DeletionIntent>("/api/cloud/deletion-intents", { method: "POST", body: JSON.stringify({ asset_id: assetId }) }),
  confirmDeletionIntent: (intentId: number) => request<DeletionIntent>(`/api/cloud/deletion-intents/${intentId}/confirm`, { method: "POST" }),
  channelSubscriptions: () => request<ChannelSubscription[]>("/api/cloud/channels"),
  saveChannelSubscription: (payload: { channel_id: string; display_name?: string; enabled: boolean; auto_transfer: boolean; require_douban_match: boolean; douban_titles: string[] }) => request<ChannelSubscription>("/api/cloud/channels", { method: "PUT", body: JSON.stringify(payload) }),
  pansouChannels: () => request<{ candidates: PansouChannelCandidate[]; message: string }>("/api/cloud/channels/pansou"),
  importPansouChannels: (channelIds: string[]) => request<{ imported: ChannelSubscription[]; existing: string[]; unrecognized: string[]; message: string }>("/api/cloud/channels/import-pansou", { method: "POST", body: JSON.stringify({ channel_ids: channelIds }) }),
  channelMessages: () => request<ChannelMessage[]>("/api/cloud/channels/messages"),
  syncChannelSources: (channelId = "") => request<{ ok: boolean; message: string; results: Array<{ channel_id: string; ok: boolean; message: string; posts: number; resources: number }> }>(`/api/cloud/channels/sync${channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ""}`, { method: "POST" }),
  testOpenList: () => request<{ ok: boolean; message: string }>("/api/openlist/test", { method: "POST" }),
  openListTasks: () => request<{ available: boolean; message: string; tasks: OpenListCopyTask[] }>("/api/openlist/tasks"),
  browseOpenList: (path: string) =>
    request<{ ok: boolean; path: string; directories: { name: string; is_dir: boolean }[] }>("/api/openlist/browse", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  browseProviderPath: (provider: "qas" | "quark" | "p115", path: string) =>
    request<{ ok: boolean; provider: "qas" | "quark" | "p115"; path: string; directories: { name: string; is_dir: boolean }[] }>("/api/config/browse-provider-path", {
      method: "POST",
      body: JSON.stringify({ provider, path }),
    }),
  browseLocalPath: (path: string) =>
    request<{ ok: boolean; root: string; path: string; exists: boolean; directories: { name: string; is_dir: boolean }[] }>("/api/config/browse-local-path", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  listOpenListEntries: (path: string) =>
    request<{ ok: boolean; path: string; entries: OpenListEntry[] }>("/api/openlist/entries", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  syncSelectedOpenList: (payload: { source_dir: string; target_dir: string; names: string[]; overwrite: boolean }) =>
    request<{ ok: boolean; message: string; job_id?: number; running?: boolean }>("/api/openlist/sync-selected", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  syncOpenListLibrary: () => request<{ ok: boolean; message: string; job_id?: number; running?: boolean; copied?: number; scanned?: number }>("/api/openlist/sync-library", { method: "POST" }),
  qasPansouStatus: () => request<{ ok: boolean; enabled?: boolean; message?: string }>("/api/config/qas-pansou"),
  setQasPansou: (enabled: boolean) =>
    request<{ ok: boolean; enabled?: boolean; message: string }>("/api/config/qas-pansou", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  discover: (mediaType: string, region: string, sort: string, genre: string, voteMin: number, page = 1, pageSize = 24, refresh = false, watchProvider = "", watchRegion = "US") =>
    request<{ results: MediaItem[]; page: number; total_pages: number; error?: string }>(
      `/api/discover?media_type=${encodeURIComponent(mediaType)}&region=${encodeURIComponent(region)}&sort=${encodeURIComponent(sort)}&genre=${encodeURIComponent(genre)}&vote_min=${voteMin}&page=${page}&page_size=${pageSize}&refresh=${refresh}&watch_provider=${encodeURIComponent(watchProvider)}&watch_region=${encodeURIComponent(watchRegion)}`,
    ),
  genres: (mediaType: string) => request<Genre[]>(`/api/genres?media_type=${encodeURIComponent(mediaType)}`),
  search: (query: string) =>
    request<{ results: MediaItem[] }>(`/api/search?q=${encodeURIComponent(query)}&media_type=all`),
  directLinkOptions: (link: string, title = "", year = "", category = "movie") =>
    request<{
      link: string;
      provider: "qas" | "p115";
      root_path: string;
      year?: string;
      options: { provider: "qas" | "p115"; path: string; label: string; category?: string }[];
    }>("/api/transfers/direct-link/options", {
      method: "POST",
      body: JSON.stringify({ link, title, year, category }),
    }),
  directLinkTransfer: (link: string, savePath: string, title = "", year = "", category = "movie") =>
    request<{ ok: boolean; provider: "qas" | "p115"; save_path: string; message: string }>("/api/transfers/direct-link", {
      method: "POST",
      body: JSON.stringify({ link, save_path: savePath, title, year, category }),
    }),
  details: (mediaType: string, tmdbId: number) =>
    request<MediaItem>(`/api/media/${encodeURIComponent(mediaType)}/${tmdbId}`),
  resources: (item: MediaItem, seasonNumber?: number, refresh = false, provider: "qas" | "quark" | "p115" = "qas") =>
    request<ResourceStatus>(
      `/api/media/${encodeURIComponent(item.media_type)}/${item.tmdb_id}/resources?title=${encodeURIComponent(item.title)}&year=${encodeURIComponent(item.year ?? "")}${seasonNumber ? `&season_number=${seasonNumber}` : ""}&refresh=${refresh}&provider=${provider}`,
    ),
  cachedResource: (item: MediaItem, seasonNumber?: number, provider: "qas" | "quark" | "p115" = "qas") =>
    request<ResourceStatus | null>(
      `/api/media/${encodeURIComponent(item.media_type)}/${item.tmdb_id}/resource-cache?provider=${provider}${seasonNumber ? `&season_number=${seasonNumber}` : ""}`,
    ),
  tracking: () => request<TrackingTask[]>("/api/tracking"),
  wishlist: () => request<WishlistItem[]>("/api/wishlist"),
  review: () => request<ReviewCandidate[]>("/api/review"),
  notifications: (unreadOnly = false) =>
    request<NotificationFeed>(`/api/notifications?limit=50&unread_only=${unreadOnly}`),
  markNotificationRead: (id?: number) =>
    request<{ ok: boolean }>("/api/notifications/read", {
      method: "POST",
      body: JSON.stringify(id === undefined ? {} : { id }),
    }),
  clearNotifications: () => request<{ ok: boolean }>("/api/notifications", { method: "DELETE" }),
  testNotificationChannel: (provider: "telegram" | "wecom" | "wecom_app") =>
    request<{ ok: boolean; provider: string; message: string }>(`/api/notifications/test/${provider}`, { method: "POST" }),
  testTelegramBot: () => request<{ ok: boolean; message: string }>("/api/config/test-telegram-bot", { method: "POST" }),
  addWishlist: (item: MediaItem, seasonNumber?: number, saveTarget: "cloud" | "local" = "cloud") =>
    request<{ ok: boolean; id: number }>("/api/wishlist", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        category: item.category,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        season_number: seasonNumber,
        save_target: saveTarget,
      }),
    }),
  deleteWishlist: (id: number) => request<{ ok: boolean }>(`/api/wishlist/${id}`, { method: "DELETE" }),
  updateWishlistSchedule: (id: number, checkHour: number) =>
    request<{ ok: boolean; next_check_at: string; tmdb_date: string }>(`/api/wishlist/${id}/schedule`, {
      method: "PATCH",
      body: JSON.stringify({ check_hour: checkHour }),
    }),
  runWishlist: (id: number) => request<{ ok: boolean; stage: string }>(`/api/wishlist/${id}/run`, { method: "POST" }),
  updateWishlistProvider: (id: number, provider: "qas" | "quark" | "p115", enabled: boolean) =>
    request<{ ok: boolean; provider: string }>(`/api/wishlist/${id}/provider`, {
      method: "PATCH",
      body: JSON.stringify({ provider, enabled }),
    }),
  confirmReview: (candidateId: number, selectedFiles: string[] = []) =>
    request<{ ok: boolean; id: number; status: string; stage: string; message?: string }>(`/api/review/${candidateId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ selected_files: selectedFiles }),
    }),
  deleteReview: (candidateId: number) =>
    request<{ ok: boolean; remaining: number }>(`/api/review/${candidateId}`, { method: "DELETE" }),
  researchReview: (jobId: number) =>
    request<{ ok: boolean; stage: string; message?: string }>(`/api/review/job/${jobId}/research`, { method: "POST" }),
  createTracking: (item: MediaItem, seasonNumber: number, saveTarget: "cloud" | "local", provider?: "qas" | "quark" | "p115") =>
    request<{ ok: boolean; id: number }>("/api/tracking", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        category: item.category,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        season_number: seasonNumber,
        save_target: saveTarget,
        provider,
      }),
    }),
  pauseTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}/pause`, { method: "POST" }),
  resumeTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}/resume`, { method: "POST" }),
  deleteTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}`, { method: "DELETE" }),
  runTracking: (id: number) => request<{ ok: boolean; id: number; status: string; stage: string; message: string; duplicate?: boolean }>(`/api/tracking/${id}/run`, { method: "POST" }),
  refreshTrackingStorage: (id: number) =>
    request<{ ok: boolean; last_saved_episode: number; message: string }>(`/api/tracking/${id}/refresh-storage`, { method: "POST" }),
  syncTrackingStorage: (id: number) =>
    request<{ ok: boolean; message: string; copied: number; scanned: number }>(`/api/tracking/${id}/sync-storage`, { method: "POST" }),
  syncSelectedTrackingEpisodes: (id: number, episodeNumbers: number[]) =>
    request<{ ok: boolean; message: string; copied: number[]; skipped: number[]; missing: number[] }>(`/api/tracking/${id}/sync-selected`, {
      method: "POST",
      body: JSON.stringify({ episode_numbers: episodeNumbers }),
    }),
  updateTrackingSchedule: (id: number, checkTime: string) =>
    request<{ ok: boolean; check_time: string; next_check_at: string }>(`/api/tracking/${id}/schedule`, {
      method: "PATCH",
      body: JSON.stringify({ check_time: checkTime }),
    }),
  updateTrackingProvider: (id: number, provider: "qas" | "quark" | "p115", enabled: boolean) =>
    request<{ ok: boolean; provider: string; save_path: string }>(`/api/tracking/${id}/provider`, {
      method: "PATCH",
      body: JSON.stringify({ provider, enabled }),
    }),
  updateTrackingSavePath: (id: number, savePath: string) =>
    request<{ ok: boolean; save_path: string; storage_refreshed: boolean; message: string }>(`/api/tracking/${id}/save-path`, {
      method: "PATCH",
      body: JSON.stringify({ save_path: savePath }),
    }),
  trackingEpisodes: (id: number) =>
    request<{
      provider: "qas" | "quark" | "p115";
      season_number: number;
      save_path: string;
      episodes: { episode_number: number; air_date: string; title: string; status: string; aired: boolean }[];
    }>(`/api/tracking/${id}/episodes`),
  fillTrackingEpisodes: (id: number, episodeNumbers: number[]) =>
    request<{ ok: boolean; id: number; status: string; stage: string; message: string; duplicate?: boolean }>(`/api/tracking/${id}/fill`, {
      method: "POST",
      body: JSON.stringify({ episode_numbers: episodeNumbers }),
    }),
  fillTrackingEpisodesFromShare: (id: number, episodeNumbers: number[], shareUrl: string) =>
    request<{ ok: boolean; id: number; status: string; stage: string; message: string; duplicate?: boolean }>(`/api/tracking/${id}/fill-from-share`, {
      method: "POST",
      body: JSON.stringify({ episode_numbers: episodeNumbers, share_url: shareUrl }),
    }),
  createTransfer: (
    item: MediaItem,
    target: "cloud" | "local",
    seasonNumber?: number,
    provider?: "qas" | "quark" | "p115" | "moviepilot_115",
    preferredShareUrl?: string,
  ) =>
    request<{ ok: boolean; id: number; save_path: string; message?: string; stage?: string; status: string }>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        category: item.category,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        target,
        season_number: seasonNumber,
        provider,
        preferred_share_urls: preferredShareUrl ? [preferredShareUrl] : [],
        simple_matching: item.media_type === "tv",
      }),
    }),
  transfer: (id: number) => request<TransferJob>(`/api/transfers/${id}`),
  mediaWorkflow: (mediaType: string, tmdbId: number) =>
    request<MediaWorkflow>(`/api/transfers/workflow/${encodeURIComponent(mediaType)}/${tmdbId}`),
  transfers: () => request<TransferJob[]>("/api/transfers"),
  wecomTransferRecords: () => request<WecomTransferRecord[]>("/api/transfers/wecom-records"),
  deleteWecomTransferRecord: (id: number) => request<{ ok: boolean; id: number }>(`/api/transfers/wecom-records/${id}`, { method: "DELETE" }),
  clearWecomTransferRecords: () => request<{ ok: boolean }>("/api/transfers/wecom-records", { method: "DELETE" }),
  stopActiveTransfers: () => request<{ ok: boolean; stopped: number }>("/api/transfers/stop-active", { method: "POST" }),
  stopTransfer: (id: number) => request<{ ok: boolean; stopped: boolean; message: string }>(`/api/transfers/${id}/stop`, { method: "POST" }),
  createTransferBatch: (
    item: MediaItem,
    items: { provider: "qas" | "quark" | "p115"; season_number?: number; episode_numbers?: number[]; preferred_share_url?: string; preferred_share_only?: boolean }[],
  ) =>
    request<{ ok: boolean; id: number; status: string; message: string; child_ids: number[] }>("/api/transfers/batches", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        category: item.category,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        target: "cloud",
        items,
        simple_matching: item.media_type === "tv",
      }),
    }),
  transferBatch: (id: number) => request<TransferBatch>(`/api/transfers/batches/${id}`),
  saveConfig: (payload: Record<string, string | number | boolean | string[] | Record<string, string>>) =>
    request<{ ok: boolean; message: string }>("/api/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
