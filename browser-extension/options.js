"use strict";

const form = document.getElementById("settingsForm");
const baseUrlInput = document.getElementById("baseUrl");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const connectButton = document.getElementById("connectButton");
const disconnectButton = document.getElementById("disconnectButton");
const statusElement = document.getElementById("status");
const statusText = document.getElementById("statusText");
const extensionVersion = document.getElementById("extensionVersion");
let currentConfig = { baseUrl: "", username: "", connected: false };

extensionVersion.textContent = displayVersion();
void initialize();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let baseUrl;
  try {
    baseUrl = normalizeBaseUrl(baseUrlInput.value);
  } catch (error) {
    setStatus("error", error.message);
    baseUrlInput.focus();
    return;
  }

  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  if (!username || !password) {
    setStatus("error", "请填写用户名和密码。");
    (!username ? usernameInput : passwordInput).focus();
    return;
  }

  const permissionPattern = originPattern(baseUrl);
  const alreadyGranted = await containsOriginPermission(permissionPattern);
  const granted = alreadyGranted || await requestOriginPermission(permissionPattern);
  if (!granted) {
    setStatus("error", "未获得该 MediaIndex 地址的访问权限。");
    return;
  }
  const previousPattern = currentConfig.baseUrl ? originPattern(currentConfig.baseUrl) : "";
  const rollbackNewPermission = !alreadyGranted && previousPattern !== permissionPattern;
  let connectionSaved = false;

  setBusy(true);
  setStatus("neutral", "正在安全连接 MediaIndex…");
  try {
    await sendToBackground({
      type: "mi:login",
      baseUrl,
      username,
      password
    });
    connectionSaved = true;
    passwordInput.value = "";
    await sendToBackground({ type: "mi:status" });

    const previousBaseUrl = currentConfig.baseUrl;
    currentConfig = { baseUrl, username, connected: true };
    if (previousBaseUrl && originPattern(previousBaseUrl) !== permissionPattern) {
      await removeOriginPermission(originPattern(previousBaseUrl));
    }
    baseUrlInput.value = baseUrl;
    disconnectButton.hidden = false;
    setStatus("success", "已连接 " + username + "，可以回到分享页转存。");
  } catch (error) {
    passwordInput.value = "";
    if (rollbackNewPermission && !connectionSaved) {
      await removeOriginPermission(permissionPattern);
    }
    setStatus("error", error.message || "连接失败，请检查填写内容。");
  } finally {
    setBusy(false);
  }
});

disconnectButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    await sendToBackground({ type: "mi:logout" });
    currentConfig = { baseUrl: "", username: "", connected: false };
    passwordInput.value = "";
    disconnectButton.hidden = true;
    setStatus("neutral", "已移除本机连接信息。");
  } catch (error) {
    setStatus("error", error.message || "移除连接失败。");
  } finally {
    setBusy(false);
  }
});

async function initialize() {
  try {
    currentConfig = await sendToBackground({ type: "mi:get-config" });
    baseUrlInput.value = currentConfig.baseUrl || "";
    usernameInput.value = currentConfig.username || "";
    disconnectButton.hidden = !currentConfig.connected;
    if (!currentConfig.connected) {
      setStatus("neutral", "填写信息后授权并连接。");
      return;
    }

    setStatus("neutral", "正在验证现有连接…");
    await sendToBackground({ type: "mi:status" });
    setStatus("success", "已连接 " + currentConfig.username + "。");
  } catch (error) {
    setStatus("error", error.message || "现有连接不可用，请重新登录。");
  }
}

function normalizeBaseUrl(value) {
  const raw = value.trim();
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("请输入完整的 http:// 或 https:// 地址。");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("MediaIndex 地址仅支持 HTTP 或 HTTPS。");
  }
  if (url.username || url.password) {
    throw new Error("请勿在地址中填写用户名或密码。");
  }
  if (url.search || url.hash) {
    throw new Error("MediaIndex 地址不能包含查询参数或页面锚点。");
  }
  return url.href.replace(/\/+$/, "");
}

function originPattern(baseUrl) {
  return new URL(baseUrl).origin + "/*";
}

function requestOriginPermission(pattern) {
  return new Promise((resolve) => {
    chrome.permissions.request({ origins: [pattern] }, (granted) => {
      if (chrome.runtime.lastError) {
        resolve(false);
        return;
      }
      resolve(granted);
    });
  });
}

function containsOriginPermission(pattern) {
  return new Promise((resolve) => {
    chrome.permissions.contains({ origins: [pattern] }, (contained) => {
      if (chrome.runtime.lastError) {
        resolve(false);
        return;
      }
      resolve(contained);
    });
  });
}

function removeOriginPermission(pattern) {
  return new Promise((resolve) => {
    chrome.permissions.remove({ origins: [pattern] }, () => resolve());
  });
}

function setBusy(busy) {
  connectButton.disabled = busy;
  disconnectButton.disabled = busy;
}

function setStatus(tone, text) {
  statusElement.dataset.tone = tone;
  statusText.textContent = text;
}

function sendToBackground(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response || response.ok !== true) {
        reject(new Error(response && response.error ? response.error.message : "扩展后台无响应。"));
        return;
      }
      resolve(response.data);
    });
  });
}

function displayVersion() {
  const manifest = chrome.runtime.getManifest();
  const version = manifest.version_name || manifest.version || "";
  return version ? "· " + (version.startsWith("v") ? version : "v" + version) : "";
}
