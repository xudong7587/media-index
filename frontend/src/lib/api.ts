export type MediaItem = {
  id: number;
  tmdb_id: number;
  media_type: "movie" | "tv" | "variety";
  title: string;
  year?: string;
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
};

export type WishlistItem = {
  id: number;
  tmdb_id: number;
  media_type: string;
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
  status: "running" | "done" | "triggered" | "needs_review" | "failed";
  stage: string;
  message: string;
  save_path: string;
};

export type ConfigStatus = {
  has_tmdb_key: boolean;
  has_qas: boolean;
  has_pansou: boolean;
  qas_base_url: string;
  pansou_url: string;
  cloud_root: string;
  local_root: string;
  category_paths: Record<string, string>;
  wishlist_default_check_hour: number;
  wishlist_scheduler_enabled: boolean;
  wishlist_poll_minutes: number;
  version: string;
};

export type Genre = {
  id: number;
  name: string;
};

export type ResourceStatus = {
  ok: boolean;
  found: boolean;
  message: string;
  title?: string;
  share_url?: string;
  file_count?: number;
};

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
    throw new Error(`HTTP ${res.status}`);
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
  discover: (mediaType: string, region: string, sort: string, genre: string, voteMin: number, page = 1, pageSize = 24) =>
    request<{ results: MediaItem[]; page: number; total_pages: number; error?: string }>(
      `/api/discover?media_type=${encodeURIComponent(mediaType)}&region=${encodeURIComponent(region)}&sort=${encodeURIComponent(sort)}&genre=${encodeURIComponent(genre)}&vote_min=${voteMin}&page=${page}&page_size=${pageSize}`,
    ),
  genres: (mediaType: string) => request<Genre[]>(`/api/genres?media_type=${encodeURIComponent(mediaType)}`),
  search: (query: string) =>
    request<{ results: MediaItem[] }>(`/api/search?q=${encodeURIComponent(query)}&media_type=all`),
  details: (mediaType: string, tmdbId: number) =>
    request<MediaItem>(`/api/media/${encodeURIComponent(mediaType)}/${tmdbId}`),
  resources: (item: MediaItem, seasonNumber?: number) =>
    request<ResourceStatus>(
      `/api/media/${encodeURIComponent(item.media_type)}/${item.tmdb_id}/resources?title=${encodeURIComponent(item.title)}&year=${encodeURIComponent(item.year ?? "")}${seasonNumber ? `&season_number=${seasonNumber}` : ""}`,
    ),
  tracking: () => request<TrackingTask[]>("/api/tracking"),
  wishlist: () => request<WishlistItem[]>("/api/wishlist"),
  review: () => request<ReviewCandidate[]>("/api/review"),
  addWishlist: (item: MediaItem, seasonNumber?: number, saveTarget: "cloud" | "local" = "cloud") =>
    request<{ ok: boolean; id: number }>("/api/wishlist", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
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
  confirmReview: (candidateId: number, selectedFiles: string[] = []) =>
    request<{ ok: boolean; stage: string; message?: string }>(`/api/review/${candidateId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ selected_files: selectedFiles }),
    }),
  researchReview: (jobId: number) =>
    request<{ ok: boolean; stage: string; message?: string }>(`/api/review/job/${jobId}/research`, { method: "POST" }),
  createTracking: (item: MediaItem, seasonNumber: number, saveTarget: "cloud" | "local") =>
    request<{ ok: boolean; id: number }>("/api/tracking", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        season_number: seasonNumber,
        save_target: saveTarget,
      }),
    }),
  pauseTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}/pause`, { method: "POST" }),
  resumeTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}/resume`, { method: "POST" }),
  deleteTracking: (id: number) => request<{ ok: boolean }>(`/api/tracking/${id}`, { method: "DELETE" }),
  runTracking: (id: number) => request<{ ok: boolean; stage: string }>(`/api/tracking/${id}/run`, { method: "POST" }),
  createTransfer: (item: MediaItem, target: "cloud" | "local", seasonNumber?: number) =>
    request<{ ok: boolean; id: number; save_path: string; message?: string; stage?: string; status: string }>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: item.tmdb_id,
        media_type: item.media_type,
        title: item.title,
        year: item.year ?? "",
        poster_url: item.poster_url ?? "",
        overview: item.overview ?? "",
        target,
        season_number: seasonNumber,
      }),
    }),
  transfer: (id: number) => request<TransferJob>(`/api/transfers/${id}`),
  saveConfig: (payload: Record<string, string | number | boolean | Record<string, string>>) =>
    request<{ ok: boolean; message: string }>("/api/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
