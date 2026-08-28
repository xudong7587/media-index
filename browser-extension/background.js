"use strict";

const CONFIG_KEYS = ["baseUrl", "username"];
const API_PATHS = Object.freeze({
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  status: "/api/auth/me",
  targets: "/api/transfers/direct-link/options",
  renamePreview: "/api/transfers/direct-link/rename-preview",
  transfers: "/api/transfers/direct-link"
});
const REQUEST_TIMEOUT_MS = 20_000;

class MediaIndexError extends Error {
  constructor(message, code, status) {
    super(message);
    this.name = "MediaIndexError";
    this.code = code || "unknown_error";
    this.status = status || null;
  }
}

void restrictLocalStorageToTrustedContexts();

chrome.runtime.onInstalled.addListener(() => {
  void restrictLocalStorageToTrustedContexts();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: serializeError(error) }));
  return true;
});

async function handleMessage(message, sender) {
  if (!message || typeof message.type !== "string") {
    throw new MediaIndexError("无效的扩展请求。", "invalid_request");
  }
  assertInternalSender(sender);

  switch (message.type) {
    case "mi:get-config":
      return getPublicConfig();
    case "mi:login":
      return login(message);
    case "mi:logout":
      return logout();
    case "mi:status":
      return authenticatedRequest(API_PATHS.status, { method: "GET" });
    case "mi:targets":
      assertSharePageSender(sender, message.shareUrl);
      return getTargets(message.shareUrl);
    case "mi:rename-preview":
      assertSharePageSender(sender, message.shareUrl);
      return getRenamePreview(message);
    case "mi:transfer":
      assertSharePageSender(sender, message.shareUrl);
      return createTransfer(message);
    case "mi:open-options":
      await chrome.runtime.openOptionsPage();
      return { opened: true };
    default:
      throw new MediaIndexError("不支持的扩展请求。", "unsupported_request");
  }
}

async function restrictLocalStorageToTrustedContexts() {
  if (!chrome.storage.local.setAccessLevel) {
    return;
  }

  try {
    await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
  } catch {
    // Older Chromium builds may not expose this MV3 hardening API.
  }
}

async function getStoredConfig() {
  const stored = await chrome.storage.local.get(CONFIG_KEYS);
  return {
    baseUrl: typeof stored.baseUrl === "string" ? stored.baseUrl : "",
    username: typeof stored.username === "string" ? stored.username : ""
  };
}

async function getPublicConfig() {
  const config = await getStoredConfig();
  return {
    baseUrl: config.baseUrl,
    username: config.username,
    connected: Boolean(config.baseUrl && config.username)
  };
}

async function login(message) {
  const baseUrl = normalizeBaseUrl(message.baseUrl);
  const username = requiredText(message.username, "用户名");
  const password = requiredText(message.password, "密码");
  await assertHostPermission(baseUrl);

  let payload;
  try {
    payload = await requestApi(baseUrl, API_PATHS.login, {
      method: "POST",
      body: { username, password }
    });
  } catch (error) {
    if (error instanceof MediaIndexError && error.status === 401) {
      throw new MediaIndexError("用户名或密码错误。", "invalid_credentials", 401);
    }
    throw error;
  }
  // Deliberately persist only these two values. Passwords and session data stay
  // with the browser-managed Cookie store.
  await chrome.storage.local.set({ baseUrl, username });
  return {
    baseUrl,
    username,
    user: payload && payload.user ? payload.user : null
  };
}

async function logout() {
  const config = await getStoredConfig();
  if (config.baseUrl) {
    try {
      await requestApi(config.baseUrl, API_PATHS.logout, { method: "POST" });
    } catch {
      // Local cleanup must still complete when the server is unavailable.
    }
  }
  await chrome.storage.local.remove(CONFIG_KEYS);

  if (config.baseUrl) {
    try {
      await chrome.permissions.remove({ origins: [originPattern(config.baseUrl)] });
    } catch {
      // Connection data is already removed; permission cleanup is best effort.
    }
  }
  return { disconnected: true };
}

async function getTargets(shareUrl) {
  const normalizedShareUrl = normalizeShareUrl(shareUrl);
  const payload = await authenticatedRequest(API_PATHS.targets, {
    method: "POST",
    body: {
      link: normalizedShareUrl,
      title: "",
      year: "",
      category: "movie"
    }
  });
  const contractVersion = Number(payload && payload.direct_link_contract_version);
  if (!Number.isInteger(contractVersion) || contractVersion < 2) {
    throw new MediaIndexError(
      "当前 MediaIndex 后台不支持命名预览和直接入库。请先更新并重启 MediaIndex 后台，再刷新扩展和分享页。",
      "backend_contract_outdated"
    );
  }
  const options = Array.isArray(payload && payload.options) ? payload.options : [];
  return {
    direct_link_contract_version: contractVersion,
    provider: payload && payload.provider,
    root_path: payload && payload.root_path,
    cloud_download_enabled: payload && payload.cloud_download_enabled === true,
    targets: options
      .filter((option) => option && typeof option.path === "string" && option.path.trim())
      .map((option) => ({
        path: option.path,
        label: typeof option.label === "string" && option.label.trim() ? option.label : option.path,
        match_rename_available: true
      }))
  };
}

async function createTransfer(message) {
  const shareUrl = normalizeShareUrl(message.shareUrl);
  const destinationMode = message.destinationMode === "library" ? "library" : "cloud_download";
  const targetPath = destinationMode === "cloud_download"
    ? requiredText(message.targetPath, "目标目录")
    : optionalText(message.targetPath);
  const title = optionalText(message.title);
  if (destinationMode === "library" && !title) {
    throw new MediaIndexError("直接入正式媒体库前请填写媒体名称。", "missing_field");
  }
  return authenticatedRequest(API_PATHS.transfers, {
    method: "POST",
    body: {
      link: shareUrl,
      save_path: targetPath,
      title,
      year: optionalText(message.year),
      category: normalizeCategory(message.category),
      match_rename: message.matchRename === true,
      destination_mode: destinationMode,
      apply_rename_plan: message.applyRenamePlan === true
    }
  });
}

async function getRenamePreview(message) {
  const shareUrl = normalizeShareUrl(message.shareUrl);
  return authenticatedRequest(API_PATHS.renamePreview, {
    method: "POST",
    body: {
      link: shareUrl,
      title: requiredText(message.title, "媒体名称"),
      year: optionalText(message.year),
      category: normalizeCategory(message.category)
    }
  });
}

async function authenticatedRequest(path, request) {
  const config = await getStoredConfig();
  if (!config.baseUrl || !config.username) {
    throw new MediaIndexError("请先在扩展设置中连接 MediaIndex。", "not_configured");
  }
  await assertHostPermission(config.baseUrl);

  try {
    return await requestApi(config.baseUrl, path, request);
  } catch (error) {
    if (error instanceof MediaIndexError && error.status === 401) {
      throw new MediaIndexError("登录已失效，请重新连接 MediaIndex。", "unauthorized", 401);
    }
    throw error;
  }
}

async function requestApi(baseUrl, path, request) {
  const headers = { Accept: "application/json" };
  const init = {
    method: request.method,
    headers,
    cache: "no-store",
    credentials: "include",
    redirect: "follow"
  };

  if (request.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(request.body);
  }

  const controller = new AbortController();
  init.signal = controller.signal;
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response;
  try {
    response = await fetch(baseUrl + path, init);
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new MediaIndexError("连接 MediaIndex 超时，请检查后台地址。", "request_timeout");
    }
    throw new MediaIndexError("无法连接 MediaIndex，请检查地址、HTTPS 证书和网络。", "network_error");
  } finally {
    clearTimeout(timeoutId);
  }

  const payload = await readResponsePayload(response);
  if (!response.ok) {
    throw new MediaIndexError(
      extractApiMessage(payload) || "MediaIndex 请求失败（HTTP " + response.status + "）。",
      "http_error",
      response.status
    );
  }
  return payload;
}

async function readResponsePayload(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new MediaIndexError("MediaIndex 返回了无法解析的响应。", "invalid_response", response.status);
  }
}

function extractApiMessage(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (typeof payload.message === "string") {
    return payload.message;
  }
  if (payload.detail && typeof payload.detail.message === "string") {
    return payload.detail.message;
  }
  return "";
}

function normalizeBaseUrl(value) {
  const raw = requiredText(value, "MediaIndex 地址");
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new MediaIndexError("请输入完整的 http:// 或 https:// 地址。", "invalid_base_url");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new MediaIndexError("MediaIndex 地址仅支持 HTTP 或 HTTPS。", "invalid_base_url");
  }
  if (url.username || url.password) {
    throw new MediaIndexError("请勿在 MediaIndex 地址中填写用户名或密码。", "invalid_base_url");
  }
  if (url.search || url.hash) {
    throw new MediaIndexError("MediaIndex 地址不能包含查询参数或页面锚点。", "invalid_base_url");
  }
  return url.href.replace(/\/+$/, "");
}

function normalizeShareUrl(value) {
  const raw = requiredText(value, "分享链接");
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new MediaIndexError("当前分享链接无效。", "invalid_share_url");
  }
  if (url.protocol !== "https:") {
    throw new MediaIndexError("当前页面不是支持的分享链接。", "unsupported_share_url");
  }

  const hostname = url.hostname.toLowerCase();
  const isQuark = hostname === "pan.quark.cn" || hostname === "www.pan.quark.cn";
  const is115 = hostname === "115.com" || hostname.endsWith(".115.com");
  const is115Cdn = hostname === "115cdn.com" || hostname.endsWith(".115cdn.com");
  const hasStandardSharePath = /^\/s\/[A-Za-z0-9_-]+/.test(url.pathname);
  const hasLegacy115SharePath =
    hostname === "share.115.com" && /^\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
  if (
    (!isQuark && !is115 && !is115Cdn) ||
    (!hasStandardSharePath && !hasLegacy115SharePath)
  ) {
    throw new MediaIndexError("当前页面不是支持的 115 或夸克分享链接。", "unsupported_share_url");
  }
  return url.href;
}

function assertInternalSender(sender) {
  if (!sender || sender.id !== chrome.runtime.id) {
    throw new MediaIndexError("拒绝来自扩展外部的请求。", "invalid_sender");
  }
}

function assertSharePageSender(sender, shareUrl) {
  const senderUrl = sender && (sender.url || (sender.tab && sender.tab.url));
  const normalizedSenderUrl = normalizeShareUrl(senderUrl);
  const normalizedRequestedUrl = normalizeShareUrl(shareUrl);
  if (normalizedSenderUrl !== normalizedRequestedUrl) {
    throw new MediaIndexError("分享链接与当前页面不一致。", "share_url_mismatch");
  }
}

function requiredText(value, label) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    throw new MediaIndexError("请填写" + label + "。", "missing_field");
  }
  return text;
}

function optionalText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeCategory(value) {
  const category = optionalText(value).toLowerCase();
  return ["movie", "tv", "variety", "concert", "documentary", "anime"].includes(category)
    ? category
    : "movie";
}

async function assertHostPermission(baseUrl) {
  const permitted = await chrome.permissions.contains({ origins: [originPattern(baseUrl)] });
  if (!permitted) {
    throw new MediaIndexError("需要先在扩展设置中授权访问该 MediaIndex 地址。", "permission_required");
  }
}

function originPattern(baseUrl) {
  return new URL(baseUrl).origin + "/*";
}

function serializeError(error) {
  if (error instanceof MediaIndexError) {
    return {
      code: error.code,
      message: error.message,
      status: error.status
    };
  }
  return {
    code: "unknown_error",
    message: "扩展发生未知错误，请重试。",
    status: null
  };
}
