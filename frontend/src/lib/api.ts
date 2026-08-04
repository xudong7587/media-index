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
  provider?: "qas" | "p115" | "";
  provider_states: TrackingProviderState[];
};

export type TrackingProviderState = {
  id: number;
  provider: "qas" | "p115";
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
  provider?: "qas" | "p115" | "";
  provider_states: WishlistProviderState[];
};

export type WishlistProviderState = {
  id: number;
  provider: "qas" | "p115";
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
  provider: "qas" | "p115" | "moviepilot_115" | "";
  job_provider?: "qas" | "p115" | "moviepilot_115" | "";
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
  status: "running" | "done" | "triggered" | "needs_review" | "failed" | "stopped";
  stage: string;
  message: string;
  save_path: string;
  provider?: "qas" | "p115" | "moviepilot_115" | "openlist" | "";
  target?: "cloud" | "local" | "";
  display_title?: string;
  media_type?: string;
  season_number?: number;
};

export type WecomTransferRecord = {
  id: number;
  display_title: string;
  media_type: string;
  provider: "qas" | "p115" | "moviepilot_115" | "openlist" | "";
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
  providers: ("qas" | "p115")[];
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
  p115_auth_mode: "cookie" | "open";
  has_p115_open: boolean;
  p115_root_path: string;
  p115_staging_path: string;
  p115_local_path: string;
  enabled_providers: ("qas" | "p115" | "moviepilot_115")[];
  default_provider: "qas" | "p115" | "moviepilot_115";
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
  provider?: "qas" | "p115";
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
  provider?: "qas" | "p115" | string;
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
    request<{ ok: boolean; message: string; root_item_count?: number }>("/api/config/test-p115", { method: "POST" }),
  testOpenList: () => request<{ ok: boolean; message: string }>("/api/openlist/test", { method: "POST" }),
  browseOpenList: (path: string) =>
    request<{ ok: boolean; path: string; directories: { name: string; is_dir: boolean }[] }>("/api/openlist/browse", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  browseProviderPath: (provider: "qas" | "p115", path: string) =>
    request<{ ok: boolean; provider: "qas" | "p115"; path: string; directories: { name: string; is_dir: boolean }[] }>("/api/config/browse-provider-path", {
      method: "POST",
      body: JSON.stringify({ provider, path }),
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
  discover: (mediaType: string, region: string, sort: string, genre: string, voteMin: number, page = 1, pageSize = 24, refresh = false) =>
    request<{ results: MediaItem[]; page: number; total_pages: number; error?: string }>(
      `/api/discover?media_type=${encodeURIComponent(mediaType)}&region=${encodeURIComponent(region)}&sort=${encodeURIComponent(sort)}&genre=${encodeURIComponent(genre)}&vote_min=${voteMin}&page=${page}&page_size=${pageSize}&refresh=${refresh}`,
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
  resources: (item: MediaItem, seasonNumber?: number, refresh = false, provider: "qas" | "p115" = "qas") =>
    request<ResourceStatus>(
      `/api/media/${encodeURIComponent(item.media_type)}/${item.tmdb_id}/resources?title=${encodeURIComponent(item.title)}&year=${encodeURIComponent(item.year ?? "")}${seasonNumber ? `&season_number=${seasonNumber}` : ""}&refresh=${refresh}&provider=${provider}`,
    ),
  cachedResource: (item: MediaItem, seasonNumber?: number, provider: "qas" | "p115" = "qas") =>
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
  updateWishlistProvider: (id: number, provider: "qas" | "p115", enabled: boolean) =>
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
  createTracking: (item: MediaItem, seasonNumber: number, saveTarget: "cloud" | "local", provider?: "qas" | "p115") =>
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
  runTracking: (id: number) => request<{ ok: boolean; stage: string; message?: string; next_check_at?: string }>(`/api/tracking/${id}/run`, { method: "POST" }),
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
  updateTrackingProvider: (id: number, provider: "qas" | "p115", enabled: boolean) =>
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
      provider: "qas" | "p115";
      season_number: number;
      save_path: string;
      episodes: { episode_number: number; air_date: string; title: string; status: string; aired: boolean }[];
    }>(`/api/tracking/${id}/episodes`),
  fillTrackingEpisodes: (id: number, episodeNumbers: number[]) =>
    request<{ ok: boolean; stage: string; message?: string }>(`/api/tracking/${id}/fill`, {
      method: "POST",
      body: JSON.stringify({ episode_numbers: episodeNumbers }),
    }),
  fillTrackingEpisodesFromShare: (id: number, episodeNumbers: number[], shareUrl: string) =>
    request<{ ok: boolean; stage: string; message?: string }>(`/api/tracking/${id}/fill-from-share`, {
      method: "POST",
      body: JSON.stringify({ episode_numbers: episodeNumbers, share_url: shareUrl }),
    }),
  createTransfer: (
    item: MediaItem,
    target: "cloud" | "local",
    seasonNumber?: number,
    provider?: "qas" | "p115" | "moviepilot_115",
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
  transfers: () => request<TransferJob[]>("/api/transfers"),
  wecomTransferRecords: () => request<WecomTransferRecord[]>("/api/transfers/wecom-records"),
  deleteWecomTransferRecord: (id: number) => request<{ ok: boolean; id: number }>(`/api/transfers/wecom-records/${id}`, { method: "DELETE" }),
  clearWecomTransferRecords: () => request<{ ok: boolean }>("/api/transfers/wecom-records", { method: "DELETE" }),
  stopActiveTransfers: () => request<{ ok: boolean; stopped: number }>("/api/transfers/stop-active", { method: "POST" }),
  stopTransfer: (id: number) => request<{ ok: boolean; stopped: boolean; message: string }>(`/api/transfers/${id}/stop`, { method: "POST" }),
  createTransferBatch: (
    item: MediaItem,
    items: { provider: "qas" | "p115"; season_number?: number; episode_numbers?: number[]; preferred_share_url?: string }[],
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
