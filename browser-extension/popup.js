"use strict";

const connection = document.getElementById("connection");
const connectionText = document.getElementById("connectionText");
const openPickerButton = document.getElementById("openPicker");
const pageHint = document.getElementById("pageHint");
const openSettingsButton = document.getElementById("openSettings");
const extensionVersion = document.getElementById("extensionVersion");
let activeTab = null;

extensionVersion.textContent = displayVersion();
void initialize();

openPickerButton.addEventListener("click", () => {
  if (!activeTab || typeof activeTab.id !== "number") {
    return;
  }
  openPickerButton.disabled = true;
  pageHint.textContent = "正在打开目录选择器…";
  chrome.tabs.sendMessage(activeTab.id, { type: "mi:open-picker" }, (response) => {
    if (chrome.runtime.lastError || !response || response.opened !== true) {
      openPickerButton.disabled = false;
      pageHint.textContent = "页面脚本尚未就绪，请刷新分享页后重试。";
      return;
    }
    window.close();
  });
});

openSettingsButton.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

async function initialize() {
  activeTab = await getActiveTab();
  const supported = Boolean(activeTab && isSupportedShareUrl(activeTab.url));
  openPickerButton.disabled = !supported;
  pageHint.textContent = supported
    ? "点击后会在分享页打开一级子目录选择器。"
    : "请先打开 115 或夸克的资源分享页。";

  try {
    const config = await sendToBackground({ type: "mi:get-config" });
    if (!config.connected) {
      setConnection("error", "尚未连接 MediaIndex");
      return;
    }
    setConnection("", "正在验证 " + config.username + "…");
    await sendToBackground({ type: "mi:status" });
    setConnection("ready", "已连接 " + config.username);
  } catch (error) {
    setConnection("error", error.message || "MediaIndex 连接不可用");
  }
}

function getActiveTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (chrome.runtime.lastError) {
        resolve(null);
        return;
      }
      resolve(tabs && tabs.length ? tabs[0] : null);
    });
  });
}

function setConnection(status, text) {
  connection.dataset.state = status;
  connectionText.textContent = text;
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

function isSupportedShareUrl(value) {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") {
      return false;
    }
    const hostname = url.hostname.toLowerCase();
    const supportedHost =
      hostname === "pan.quark.cn" ||
      hostname === "www.pan.quark.cn" ||
      hostname === "115.com" ||
      hostname.endsWith(".115.com") ||
      hostname === "115cdn.com" ||
      hostname.endsWith(".115cdn.com");
    const standardPath = /^\/s\/[A-Za-z0-9_-]+/.test(url.pathname);
    const legacy115Path =
      hostname === "share.115.com" && /^\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
    return supportedHost && (standardPath || legacy115Path);
  } catch {
    return false;
  }
}

function displayVersion() {
  const manifest = chrome.runtime.getManifest();
  const version = manifest.version_name || manifest.version || "";
  return version ? "· " + (version.startsWith("v") ? version : "v" + version) : "";
}
