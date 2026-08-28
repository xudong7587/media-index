(() => {
  "use strict";

  const TRIGGER_HOST_ID = "media-index-transfer-trigger";
  const DIALOG_HOST_ID = "media-index-transfer-dialog";
  const OFFICIAL_ACTION_PATTERN = /转存|保存(?:到|至).{0,8}(?:网盘|115|夸克)|存到网盘/;
  const state = {
    triggerHost: null,
    dialogHost: null,
    dialog: null,
    busy: false,
    placementTimer: null,
    lastFocused: null
  };

  if (!isSupportedShareUrl(window.location.href)) {
    return;
  }

  start();

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.type !== "mi:open-picker") {
      return false;
    }
    void openPicker();
    sendResponse({ opened: true });
    return false;
  });

  function start() {
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", start, { once: true });
      return;
    }
    ensureTrigger();
    placeTrigger();
    observePageChanges();
  }

  function ensureTrigger() {
    if (state.triggerHost) {
      return state.triggerHost;
    }

    const host = document.createElement("div");
    host.id = TRIGGER_HOST_ID;
    host.dataset.mediaIndexExtension = "true";
    host.dataset.placement = "floating";
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = [
      ":host { display: inline-flex; align-items: center; margin-inline-start: 8px; vertical-align: middle; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; }",
      ":host([data-placement=floating]) { position: fixed; right: 24px; bottom: 24px; z-index: 2147483639; margin: 0; }",
      ".trigger { box-sizing: border-box; display: inline-flex; height: 36px; align-items: center; justify-content: center; gap: 7px; padding: 0 13px; border: 1px solid rgba(46, 101, 220, .28); border-radius: 10px; background: #f7faff; color: #2159ce; box-shadow: 0 1px 2px rgba(21, 48, 92, .08); cursor: pointer; font: 600 13px/1 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; white-space: nowrap; transition: transform 140ms cubic-bezier(.22, 1, .36, 1), border-color 140ms cubic-bezier(.22, 1, .36, 1), background-color 140ms cubic-bezier(.22, 1, .36, 1), box-shadow 140ms cubic-bezier(.22, 1, .36, 1); }",
      ":host([data-placement=floating]) .trigger { height: 42px; padding-inline: 15px; border-color: rgba(46, 101, 220, .25); background: #ffffff; box-shadow: 0 12px 32px rgba(23, 47, 91, .20); }",
      ".trigger:focus-visible { outline: 3px solid rgba(65, 126, 248, .28); outline-offset: 2px; }",
      ".trigger:active { transform: scale(.97); }",
      ".icon { width: 20px; height: 20px; object-fit: contain; }",
      "@media (hover: hover) { .trigger:hover { border-color: rgba(39, 94, 211, .52); background: #eef4ff; box-shadow: 0 5px 16px rgba(31, 80, 179, .14); } }",
      "@media (prefers-reduced-motion: reduce) { .trigger { transition: none; } }"
    ].join("\n");

    const button = document.createElement("button");
    button.type = "button";
    button.className = "trigger";
    button.title = "选择 MediaIndex 转存方式";
    button.setAttribute("aria-haspopup", "dialog");

    const icon = document.createElement("img");
    icon.className = "icon";
    icon.alt = "";
    icon.src = chrome.runtime.getURL("icons/media-index-icon.png");

    const label = document.createElement("span");
    label.textContent = "转存到 MediaIndex";
    button.append(icon, label);
    button.addEventListener("click", (event) => {
      if (!event.isTrusted) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      void openPicker();
    });

    shadow.append(style, button);
    state.triggerHost = host;
    return host;
  }

  function placeTrigger() {
    state.placementTimer = null;
    if (!document.body) {
      return;
    }
    if (!isSupportedShareUrl(window.location.href)) {
      if (state.triggerHost && state.triggerHost.isConnected) {
        state.triggerHost.remove();
      }
      if (state.dialogHost) {
        state.dialogHost.hidden = true;
      }
      return;
    }
    const host = ensureTrigger();
    const officialAction = findOfficialTransferAction();
    if (officialAction && officialAction.parentElement) {
      const insertionAnchor = officialInsertionAnchor(officialAction, host);
      if (insertionAnchor.nextSibling !== host) {
        insertionAnchor.insertAdjacentElement("afterend", host);
      }
      host.dataset.placement = "inline";
      return;
    }

    if (!host.isConnected || host.dataset.placement !== "floating") {
      document.body.append(host);
      host.dataset.placement = "floating";
    }
  }

  function findOfficialTransferAction() {
    const hostname = window.location.hostname.toLowerCase();
    if (hostname === "pan.quark.cn" || hostname === "www.pan.quark.cn") {
      const exactQuarkSave = document.querySelector("button.ant-btn.share-save");
      if (exactQuarkSave instanceof HTMLElement && isVisible(exactQuarkSave)) {
        return exactQuarkSave;
      }
      const quarkSave = firstVisibleMatch([".share-btns button.share-save", ".share-btns button"]);
      if (quarkSave) {
        return quarkSave;
      }
    } else {
      const legacy115Save = document.querySelector("#js-menu a[btn=save]");
      if (legacy115Save instanceof HTMLElement && isVisible(legacy115Save)) {
        return legacy115Save;
      }
      const headerActions = document.querySelectorAll(
        ".share-page-header-right button, .share-page-header-right a, .share-page-header-right [role=button]"
      );
      for (const action of headerActions) {
        if (
          action instanceof HTMLElement &&
          normalizeText(action.innerText || action.textContent || "") === "转存" &&
          isVisible(action)
        ) {
          return action;
        }
      }
    }

    const candidates = document.querySelectorAll(
      "button, a, [role=button], [class*=btn], [class*=button]"
    );
    let best = null;
    let bestScore = -1;

    for (const element of candidates) {
      if (!(element instanceof HTMLElement) || element.id === TRIGGER_HOST_ID) {
        continue;
      }
      const text = normalizeText(element.innerText || element.textContent || "");
      if (!text || text.length > 40 || !OFFICIAL_ACTION_PATTERN.test(text) || !isVisible(element)) {
        continue;
      }

      let score = 0;
      if (element.matches("button, [role=button]")) {
        score += 4;
      }
      if (/^(转存|转存到网盘|保存到网盘|存到网盘)$/.test(text)) {
        score += 5;
      }
      if (/transfer|save/i.test(String(element.className))) {
        score += 2;
      }
      if (score > bestScore) {
        best = element;
        bestScore = score;
      }
    }
    return best;
  }

  function officialInsertionAnchor(action, host) {
    const sibling = nextVisibleSibling(action, host);
    if (!sibling || !isSplitButtonCompanion(action, sibling)) {
      return action;
    }
    const parent = action.parentElement;
    if (!parent) {
      return sibling;
    }
    const visibleChildren = Array.from(parent.children).filter(
      (child) => child === host || (child instanceof HTMLElement && isVisible(child))
    );
    const actionRect = action.getBoundingClientRect();
    const siblingRect = sibling.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    const compactPair = visibleChildren.length <= 3 &&
      parentRect.width <= actionRect.width + siblingRect.width + 16;
    return compactPair ? parent : sibling;
  }

  function nextVisibleSibling(action, host) {
    let sibling = action.nextElementSibling;
    while (sibling === host) {
      sibling = sibling.nextElementSibling;
    }
    return sibling instanceof HTMLElement && isVisible(sibling) ? sibling : null;
  }

  function isSplitButtonCompanion(action, sibling) {
    const actionRect = action.getBoundingClientRect();
    const siblingRect = sibling.getBoundingClientRect();
    const text = normalizeText(sibling.innerText || sibling.textContent || "");
    const hint = [
      sibling.getAttribute("aria-label"),
      sibling.getAttribute("title"),
      sibling.getAttribute("aria-haspopup"),
      String(sibling.className || "")
    ].join(" ");
    const sameHeight = Math.abs(actionRect.height - siblingRect.height) <= 4;
    const adjacent = Math.abs(siblingRect.left - actionRect.right) <= 6;
    const narrow = siblingRect.width > 0 && siblingRect.width <= 64;
    return sameHeight && adjacent && narrow && (text.length <= 2 || /更多|展开|下拉|menu|drop/i.test(hint));
  }

  function firstVisibleMatch(selectors) {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (
          element instanceof HTMLElement &&
          isVisible(element) &&
          OFFICIAL_ACTION_PATTERN.test(normalizeText(element.innerText || element.textContent || ""))
        ) {
          return element;
        }
      }
    }
    return null;
  }

  function isVisible(element) {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity || 1) !== 0 &&
      rect.width > 0 &&
      rect.height > 0
    );
  }

  function observePageChanges() {
    const observer = new MutationObserver(() => {
      if (state.placementTimer !== null) {
        return;
      }
      state.placementTimer = window.setTimeout(placeTrigger, 500);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  async function openPicker() {
    const dialog = ensureDialog();
    if (state.busy) {
      dialog.panel.focus();
      return;
    }

    state.lastFocused = document.activeElement;
    state.dialogHost.hidden = false;
    renderLoading();
    state.busy = true;
    dialog.panel.focus();

    try {
      const targets = await sendToBackground({
        type: "mi:targets",
        shareUrl: window.location.href
      });
      renderTargets(targets);
    } catch (error) {
      renderError(error);
    } finally {
      state.busy = false;
    }
  }

  function ensureDialog() {
    if (state.dialog) {
      return state.dialog;
    }

    const host = document.createElement("div");
    host.id = DIALOG_HOST_ID;
    host.dataset.mediaIndexExtension = "true";
    host.hidden = true;
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = dialogStyles();

    const backdrop = createElement("div", "backdrop");
    const panel = createElement("section", "panel");
    panel.tabIndex = -1;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "mi-dialog-title");

    const header = createElement("header", "header");
    const brand = createElement("div", "brand");
    const icon = document.createElement("img");
    icon.className = "brand-icon";
    icon.alt = "";
    icon.src = chrome.runtime.getURL("icons/media-index-icon.png");
    const titleGroup = createElement("div", "title-group");
    const eyebrow = createElement("span", "eyebrow", "MEDIAINDEX" + extensionVersionLabel());
    const title = createElement("h2", "title", "转存到 MediaIndex");
    title.id = "mi-dialog-title";
    titleGroup.append(eyebrow, title);
    brand.append(icon, titleGroup);

    const closeButton = createElement("button", "close", "×");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "关闭目录选择器");
    closeButton.addEventListener("click", closeDialog);
    header.append(brand, closeButton);

    const content = createElement("div", "content");
    panel.append(header, content);
    backdrop.append(panel);
    shadow.append(style, backdrop);
    document.body.append(host);

    backdrop.addEventListener("mousedown", (event) => {
      if (event.isTrusted && event.target === backdrop) {
        closeDialog();
      }
    });
    shadow.addEventListener("keydown", handleDialogKeydown);

    state.dialogHost = host;
    state.dialog = { shadow, backdrop, panel, content, closeButton };
    return state.dialog;
  }

  function dialogStyles() {
    return [
      ":host { position: fixed; inset: 0; z-index: 2147483646; display: block; color: #17223b; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; }",
      ":host([hidden]) { display: none; }",
      "* { box-sizing: border-box; }",
      ".backdrop { position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(15, 24, 43, .48); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); }",
      ".panel { width: min(536px, 100%); max-height: min(680px, calc(100vh - 48px)); overflow: hidden; border: 1px solid rgba(39, 65, 115, .14); border-radius: 18px; background: #ffffff; box-shadow: 0 28px 72px rgba(11, 24, 49, .28); outline: none; }",
      ".header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px 15px; border-bottom: 1px solid #edf0f5; }",
      ".brand { display: flex; min-width: 0; align-items: center; gap: 11px; }",
      ".brand-icon { width: 34px; height: 34px; object-fit: contain; }",
      ".title-group { display: flex; min-width: 0; flex-direction: column; gap: 2px; }",
      ".eyebrow { color: #6b7b9b; font-size: 10px; font-weight: 700; letter-spacing: .14em; }",
      ".title { margin: 0; color: #17223b; font-size: 18px; font-weight: 700; line-height: 1.3; }",
      ".close { width: 32px; height: 32px; flex: none; border: 0; border-radius: 9px; background: transparent; color: #66738d; cursor: pointer; font: 400 24px/28px Arial, sans-serif; transition: transform 140ms cubic-bezier(.22, 1, .36, 1), background-color 140ms cubic-bezier(.22, 1, .36, 1); }",
      ".close:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid rgba(66, 125, 244, .26); outline-offset: 2px; }",
      ".close:active, button:active { transform: scale(.97); }",
      ".content { max-height: calc(min(680px, 100vh - 48px) - 70px); overflow-y: auto; padding: 20px; }",
      ".loading { display: grid; min-height: 230px; place-items: center; color: #687691; text-align: center; }",
      ".spinner { width: 30px; height: 30px; margin: 0 auto 13px; border: 3px solid #dfe7f8; border-top-color: #3676ed; border-radius: 50%; animation: mi-spin .8s linear infinite; }",
      "@keyframes mi-spin { to { transform: rotate(360deg); } }",
      ".summary { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; }",
      ".provider { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; background: #eef4ff; color: #2a62d2; font-size: 12px; font-weight: 700; }",
      ".root { min-width: 0; color: #75829b; font-size: 12px; overflow-wrap: anywhere; }",
      ".scope-note { margin: -2px 0 12px; padding: 9px 11px; border: 1px solid #dce6f7; border-radius: 9px; background: #f6f9ff; color: #5c6f90; font-size: 12px; line-height: 1.5; }",
      ".scope-note.direct { margin-top: 14px; }",
      ".mode-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }",
      ".mode-card { display: flex; align-items: flex-start; gap: 9px; min-width: 0; padding: 12px; border: 1px solid #dfe5ef; border-radius: 12px; background: #fff; cursor: pointer; transition: border-color 140ms ease, background-color 140ms ease, box-shadow 140ms ease; }",
      ".mode-card.selected { border-color: #6e9aef; background: #f5f8ff; box-shadow: 0 0 0 2px rgba(67, 119, 226, .08); }",
      ".mode-card.disabled { cursor: not-allowed; opacity: .58; }",
      ".mode-card input { width: 17px; height: 17px; flex: none; margin: 1px 0 0; accent-color: #3476ed; }",
      ".mode-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }",
      ".mode-title { color: #1c2a44; font-size: 14px; font-weight: 700; }",
      ".mode-flow { color: #3269cb; font-size: 11px; font-weight: 650; line-height: 1.45; }",
      ".mode-note { color: #7b879b; font-size: 11px; line-height: 1.4; }",
      ".fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; margin-top: 16px; }",
      ".field { display: flex; min-width: 0; flex-direction: column; gap: 6px; }",
      ".field.wide { grid-column: 1 / -1; }",
      ".field-label { color: #43516b; font-size: 12px; font-weight: 700; }",
      ".field-help, .inline-help { color: #7d899d; font-size: 11px; line-height: 1.45; }",
      ".text-input { width: 100%; min-height: 38px; padding: 0 10px; border: 1px solid #dbe2ed; border-radius: 9px; background: #fff; color: #1d2940; font: 13px/1.2 Inter, ui-sans-serif, system-ui, sans-serif; }",
      ".preview-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-top: 12px; }",
      ".preview-box { margin-top: 10px; padding: 11px; border: 1px solid #d8e5fb; border-radius: 10px; background: #f7faff; }",
      ".preview-box[hidden], .mode-panel[hidden] { display: none; }",
      ".preview-heading { color: #263b64; font-size: 12px; font-weight: 750; }",
      ".preview-path { margin-top: 4px; color: #687894; font-size: 11px; overflow-wrap: anywhere; }",
      ".preview-list { display: grid; gap: 7px; margin-top: 9px; }",
      ".preview-row { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 7px; align-items: center; padding-top: 7px; border-top: 1px solid #e4ebf7; font-size: 11px; }",
      ".preview-source { color: #6f7c91; overflow-wrap: anywhere; }",
      ".preview-arrow { color: #91a0b8; }",
      ".preview-target { color: #245dbf; font-weight: 650; overflow-wrap: anywhere; }",
      ".mode-panel { margin-top: 16px; }",
      ".option { display: flex; align-items: flex-start; gap: 11px; padding: 13px 14px; border: 1px solid #e3e8f1; border-radius: 12px; background: #fafbfd; cursor: pointer; }",
      ".option input { width: 18px; height: 18px; flex: none; margin: 1px 0 0; accent-color: #3476ed; }",
      ".option-copy { display: flex; flex-direction: column; gap: 3px; }",
      ".option-title { color: #1b2942; font-size: 14px; font-weight: 650; line-height: 1.35; }",
      ".option-help { color: #7a879d; font-size: 12px; line-height: 1.45; }",
      ".notice { margin-top: 9px; padding: 9px 11px; border: 1px solid #f2d8a9; border-radius: 9px; background: #fff9ed; color: #8a5b12; font-size: 12px; line-height: 1.5; }",
      ".notice[hidden] { display: none; }",
      ".section-label { margin: 20px 0 9px; color: #52617d; font-size: 12px; font-weight: 700; letter-spacing: .02em; }",
      ".section-label.compact { margin-top: 0; }",
      ".targets { display: grid; gap: 8px; }",
      ".target { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px 13px; border: 1px solid #dde4ef; border-radius: 11px; background: #ffffff; color: inherit; cursor: pointer; text-align: left; transition: transform 140ms cubic-bezier(.22, 1, .36, 1), border-color 140ms cubic-bezier(.22, 1, .36, 1), background-color 140ms cubic-bezier(.22, 1, .36, 1), box-shadow 140ms cubic-bezier(.22, 1, .36, 1); }",
      ".target[disabled] { cursor: wait; opacity: .58; }",
      ".target-copy { min-width: 0; }",
      ".target-label { display: block; color: #1d2b45; font-size: 14px; font-weight: 650; line-height: 1.35; overflow-wrap: anywhere; }",
      ".target-path { display: block; margin-top: 3px; color: #7a879b; font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }",
      ".target-badge { flex: none; padding: 4px 7px; border-radius: 7px; background: #edf8f4; color: #26735a; font-size: 11px; font-weight: 700; white-space: nowrap; }",
      ".target-badge.plain { background: #f2f3f6; color: #6d7789; }",
      ".empty { padding: 24px 16px; border: 1px dashed #dbe1eb; border-radius: 11px; color: #77849a; font-size: 13px; text-align: center; }",
      ".status-line { min-height: 18px; margin-top: 10px; color: #5d6c86; font-size: 12px; line-height: 1.5; }",
      ".error-card, .success-card { display: grid; min-height: 240px; place-items: center; padding: 18px; text-align: center; }",
      ".state-icon { display: grid; width: 50px; height: 50px; margin: 0 auto 14px; place-items: center; border-radius: 50%; background: #fff0ef; color: #c8463a; font-size: 24px; font-weight: 700; }",
      ".success-card .state-icon { background: #eaf8f2; color: #197456; }",
      ".state-title { margin: 0; color: #1c2941; font-size: 17px; font-weight: 700; }",
      ".state-copy { max-width: 390px; margin: 8px auto 0; color: #718099; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }",
      ".actions { display: flex; justify-content: center; gap: 9px; margin-top: 18px; }",
      ".primary, .secondary { min-height: 36px; padding: 0 14px; border-radius: 9px; cursor: pointer; font: 650 13px/1 Inter, ui-sans-serif, system-ui, sans-serif; }",
      ".primary { border: 1px solid #326fdf; background: #3476ed; color: #ffffff; }",
      ".secondary { border: 1px solid #dbe2ed; background: #ffffff; color: #42516c; }",
      ".submit-wide { width: 100%; min-height: 42px; margin-top: 2px; }",
      "@media (hover: hover) { .close:hover { background: #f1f4f8; } .target:hover { border-color: #83a8ee; background: #f9fbff; box-shadow: 0 6px 18px rgba(31, 72, 150, .09); } .primary:hover { background: #2869de; } .secondary:hover { background: #f7f9fc; } }",
      "@media (max-width: 560px) { .backdrop { align-items: end; padding: 0; } .panel { width: 100%; max-height: 88vh; border-radius: 18px 18px 0 0; } .content { max-height: calc(88vh - 70px); } .mode-group { grid-template-columns: 1fr; } }",
      "@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 1.6s; } .close, .target, .primary, .secondary { transition: none; } }"
    ].join("\n");
  }

  function renderLoading() {
    const content = state.dialog.content;
    const box = createElement("div", "loading");
    const inner = document.createElement("div");
    inner.append(
      createElement("div", "spinner"),
      createElement("div", "", "正在读取 MediaIndex 转存选项…")
    );
    box.append(inner);
    content.replaceChildren(box);
  }

  function renderTargets(payload) {
    const content = state.dialog.content;
    const targets = Array.isArray(payload && payload.targets)
      ? payload.targets.filter((target) => target && typeof target.path === "string" && target.path.trim())
      : [];
    const cloudDownloadEnabled = payload && payload.cloud_download_enabled === true;
    const form = {
      mode: cloudDownloadEnabled ? "cloud_download" : "library",
      title: document.createElement("input"),
      year: document.createElement("input"),
      category: document.createElement("select"),
      organize: document.createElement("input")
    };

    const summary = createElement("div", "summary");
    summary.append(
      createElement("span", "provider", providerName(payload && payload.provider)),
      createElement("span", "root", "当前分享页网址将原样交给 MediaIndex")
    );
    const flowTitle = createElement("div", "section-label compact", "选择处理链路");
    const modeGroup = createElement("div", "mode-group");
    const cloudMode = createModeCard(
      "cloud_download",
      "云下载后整理",
      "分享 → 云下载子目录 → 自动识别整理 → 正式媒体库",
      cloudDownloadEnabled ? "点击子目录后立即转存" : "MediaIndex 当前未启用这条链路",
      !cloudDownloadEnabled
    );
    const libraryMode = createModeCard(
      "library",
      "直接入正式媒体库",
      "分享 → 规则命名 → 正式媒体库",
      "跳过云下载文件夹；未启用云下载时也可使用",
      false
    );
    modeGroup.append(cloudMode.card, libraryMode.card);

    const fields = createElement("div", "fields");
    const titleField = createElement("label", "field wide");
    titleField.append(createElement("span", "field-label", "媒体名称（用于识别）"));
    form.title.type = "text";
    form.title.className = "text-input";
    form.title.maxLength = 200;
    form.title.placeholder = "例如：流浪地球2";
    titleField.append(
      form.title,
      createElement("span", "field-help", "这是媒体名称，不是完整文件名；直接入库时必填。")
    );
    const categoryField = createElement("label", "field");
    categoryField.append(createElement("span", "field-label", "类型"));
    form.category.className = "text-input";
    for (const [value, label] of [
      ["movie", "电影"], ["tv", "电视剧"], ["variety", "综艺"],
      ["concert", "演唱会"], ["documentary", "纪录片"], ["anime", "动漫"]
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      form.category.append(option);
    }
    categoryField.append(form.category);
    const yearField = createElement("label", "field");
    yearField.append(createElement("span", "field-label", "年份（可选）"));
    form.year.type = "text";
    form.year.inputMode = "numeric";
    form.year.className = "text-input";
    form.year.maxLength = 10;
    form.year.placeholder = "2024";
    yearField.append(form.year);
    fields.append(titleField, categoryField, yearField);

    const previewActions = createElement("div", "preview-actions");
    const previewButton = createElement("button", "secondary", "生成默认命名预览");
    previewButton.type = "button";
    const previewHint = createElement("span", "inline-help", "调用 MediaIndex 当前默认规则，不会执行转存");
    previewActions.append(previewButton, previewHint);
    const previewBox = createElement("div", "preview-box");
    previewBox.hidden = true;

    const cloudPanel = createElement("div", "mode-panel");
    const organizeOption = createElement("label", "option");
    form.organize.type = "checkbox";
    form.organize.checked = true;
    const organizeCopy = createElement("span", "option-copy");
    organizeCopy.append(
      createElement("span", "option-title", "转存完成后继续自动整理入库"),
      createElement("span", "option-help", "MediaIndex 自动识别媒体，并按后台规则整理、生成 STRM、通知 Emby 刷新。")
    );
    organizeOption.append(form.organize, organizeCopy);
    const cloudRoot = createElement(
      "div",
      "scope-note",
      payload && payload.root_path ? "云下载根目录：" + payload.root_path : "请选择云下载根目录的直属子目录"
    );
    const targetLabel = createElement("div", "section-label", "点击子目录立即转存");
    const targetList = createElement("div", "targets");
    if (!targets.length) {
      targetList.append(createElement("div", "empty", "MediaIndex 未返回可用的云下载子目录。"));
    } else {
      for (const target of targets) {
        const button = createElement("button", "target");
        button.type = "button";
        const copy = createElement("span", "target-copy");
        copy.append(
          createElement("span", "target-label", target.label || target.path),
          createElement("span", "target-path", target.path)
        );
        button.append(copy, createElement("span", "target-badge", "转存"));
        button.addEventListener("click", (event) => {
          if (!event.isTrusted) {
            return;
          }
          void submitTransfer({
            mode: "cloud_download",
            target,
            form,
            controls: content,
            statusLine
          });
        });
        targetList.append(button);
      }
    }
    cloudPanel.append(organizeOption, cloudRoot, targetLabel, targetList);

    const libraryPanel = createElement("div", "mode-panel");
    const libraryFlow = createElement(
      "div",
      "scope-note direct",
      "MediaIndex 将按上方名称和默认命名规则直接写入正式媒体库，不经过云下载文件夹。"
    );
    const libraryButton = createElement("button", "primary submit-wide", "转存到正式媒体库");
    libraryButton.type = "button";
    libraryButton.addEventListener("click", (event) => {
      if (!event.isTrusted) {
        return;
      }
      void submitTransfer({
        mode: "library",
        target: { path: "", label: "正式媒体库" },
        form,
        controls: content,
        statusLine
      });
    });
    libraryPanel.append(libraryFlow, libraryButton);

    const statusLine = createElement("div", "status-line");
    statusLine.setAttribute("aria-live", "polite");

    function syncMode() {
      form.mode = libraryMode.input.checked ? "library" : "cloud_download";
      cloudMode.card.classList.toggle("selected", form.mode === "cloud_download");
      libraryMode.card.classList.toggle("selected", form.mode === "library");
      cloudPanel.hidden = form.mode !== "cloud_download";
      libraryPanel.hidden = form.mode !== "library";
      titleField.querySelector(".field-label").textContent = form.mode === "library"
        ? "媒体名称（用于识别，必填）"
        : "媒体名称（用于识别，可选）";
      statusLine.textContent = "";
    }
    cloudMode.input.checked = form.mode === "cloud_download";
    libraryMode.input.checked = form.mode === "library";
    cloudMode.input.addEventListener("change", syncMode);
    libraryMode.input.addEventListener("change", syncMode);
    syncMode();

    previewButton.addEventListener("click", (event) => {
      if (!event.isTrusted) {
        return;
      }
      void loadRenamePreview(form, previewButton, previewBox, statusLine);
    });
    for (const field of [form.title, form.year, form.category]) {
      field.addEventListener("input", () => {
        previewBox.hidden = true;
      });
      field.addEventListener("change", () => {
        previewBox.hidden = true;
      });
    }

    content.replaceChildren(
      summary,
      flowTitle,
      modeGroup,
      fields,
      previewActions,
      previewBox,
      cloudPanel,
      libraryPanel,
      statusLine
    );
  }

  function createModeCard(value, title, flow, note, disabled) {
    const card = createElement("label", "mode-card" + (disabled ? " disabled" : ""));
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mi-destination-mode";
    input.value = value;
    input.disabled = disabled;
    const copy = createElement("span", "mode-copy");
    copy.append(
      createElement("span", "mode-title", title),
      createElement("span", "mode-flow", flow),
      createElement("span", "mode-note", note)
    );
    card.append(input, copy);
    return { card, input };
  }

  async function loadRenamePreview(form, button, previewBox, statusLine) {
    if (state.busy) {
      return;
    }
    const title = form.title.value.trim();
    if (!title) {
      statusLine.textContent = "请先填写媒体名称，再生成默认命名预览。";
      form.title.focus();
      return;
    }
    state.busy = true;
    button.disabled = true;
    button.textContent = "正在生成预览…";
    statusLine.textContent = "正在读取分享内容并套用 MediaIndex 默认命名规则…";
    try {
      const preview = await sendToBackground({
        type: "mi:rename-preview",
        shareUrl: window.location.href,
        title,
        year: form.year.value,
        category: form.category.value
      });
      renderRenamePreview(previewBox, preview);
      if (!form.year.value.trim() && preview && preview.year) {
        form.year.value = preview.year;
      }
      statusLine.textContent = "命名预览已生成；确认后可继续选择目录或直接入库。";
    } catch (error) {
      previewBox.hidden = true;
      statusLine.textContent = error && error.message ? error.message : "命名预览生成失败，请重试。";
    } finally {
      button.disabled = false;
      button.textContent = "生成默认命名预览";
      state.busy = false;
    }
  }

  function renderRenamePreview(box, preview) {
    const files = Array.isArray(preview && preview.files) ? preview.files : [];
    const heading = createElement("div", "preview-heading", "MediaIndex 默认命名预览");
    const path = createElement("div", "preview-path", "正式媒体库路径：" + ((preview && preview.save_path) || "由后台生成"));
    const list = createElement("div", "preview-list");
    for (const file of files) {
      const row = createElement("div", "preview-row");
      row.append(
        createElement("span", "preview-source", file.source_name || "源文件"),
        createElement("span", "preview-arrow", "→"),
        createElement("span", "preview-target", file.target_name || "按原名")
      );
      list.append(row);
    }
    if (!files.length) {
      list.append(createElement("div", "inline-help", "没有返回可预览的视频文件。"));
    }
    box.replaceChildren(heading, path, list);
    box.hidden = false;
  }

  async function submitTransfer({ mode, target, form, controls, statusLine }) {
    if (state.busy) {
      return;
    }
    const title = form.title.value.trim();
    if (mode === "library" && !title) {
      statusLine.textContent = "直接入正式媒体库前请填写媒体名称。";
      form.title.focus();
      return;
    }
    state.busy = true;
    for (const button of controls.querySelectorAll("button")) {
      button.disabled = true;
    }
    statusLine.textContent = mode === "library"
      ? "正在按 MediaIndex 默认命名规则提交正式媒体库转存…"
      : form.organize.checked
        ? "正在提交云下载转存与后续整理任务…"
        : "正在按原路径提交云下载转存…";

    try {
      await sendToBackground({
        type: "mi:transfer",
        shareUrl: window.location.href,
        targetPath: target.path,
        title,
        year: form.year.value,
        category: form.category.value,
        matchRename: mode === "cloud_download" && form.organize.checked,
        destinationMode: mode,
        applyRenamePlan: mode === "library" || Boolean(title)
      });
      renderSuccess(target, mode, form.organize.checked, Boolean(title));
    } catch (error) {
      statusLine.textContent = error && error.message ? error.message : "转存提交失败，请重试。";
      for (const button of controls.querySelectorAll("button")) {
        button.disabled = false;
      }
    } finally {
      state.busy = false;
    }
  }

  function renderSuccess(target, mode, organize, renamed) {
    const card = createElement("div", "success-card");
    const inner = document.createElement("div");
    let detail;
    if (mode === "library") {
      detail = "已跳过云下载文件夹，将按 MediaIndex 默认命名规则直接转存到正式媒体库。";
    } else if (organize) {
      detail = "目标目录：" + (target.label || target.path) + "。MediaIndex 将继续自动整理、生成 STRM 并通知 Emby 刷新。";
    } else {
      detail = "目标目录：" + (target.label || target.path) + "。本次" + (renamed ? "按预览命名" : "按原名称") + "转存，不触发后续整理入库。";
    }
    inner.append(
      createElement("div", "state-icon", "✓"),
      createElement("h3", "state-title", "转存任务已提交"),
      createElement("p", "state-copy", detail)
    );
    const actions = createElement("div", "actions");
    const doneButton = createElement("button", "primary", "完成");
    doneButton.type = "button";
    doneButton.addEventListener("click", closeDialog);
    actions.append(doneButton);
    inner.append(actions);
    card.append(inner);
    state.dialog.content.replaceChildren(card);
    doneButton.focus();
  }

  function renderError(error) {
    const code = error && error.code ? error.code : "";
    const card = createElement("div", "error-card");
    const inner = document.createElement("div");
    inner.append(
      createElement("div", "state-icon", "!"),
      createElement(
        "h3",
        "state-title",
        code === "not_configured" || code === "unauthorized" || code === "permission_required"
          ? "需要连接 MediaIndex"
          : code === "backend_contract_outdated"
            ? "需要更新 MediaIndex 后台"
            : "暂时无法读取目录"
      ),
      createElement(
        "p",
        "state-copy",
        error && error.message ? error.message : "请检查 MediaIndex 后台后重试。"
      )
    );
    const actions = createElement("div", "actions");
    if (code === "not_configured" || code === "unauthorized" || code === "permission_required") {
      const settingsButton = createElement("button", "primary", "打开扩展设置");
      settingsButton.type = "button";
      settingsButton.addEventListener("click", () => {
        void sendToBackground({ type: "mi:open-options" });
        closeDialog();
      });
      actions.append(settingsButton);
    }
    const retryButton = createElement("button", "secondary", "重试");
    retryButton.type = "button";
    retryButton.addEventListener("click", () => void openPicker());
    actions.append(retryButton);
    inner.append(actions);
    card.append(inner);
    state.dialog.content.replaceChildren(card);
  }

  function closeDialog() {
    if (!state.dialogHost || state.busy) {
      return;
    }
    state.dialogHost.hidden = true;
    if (state.lastFocused && typeof state.lastFocused.focus === "function") {
      state.lastFocused.focus();
    }
  }

  function handleDialogKeydown(event) {
    if (state.dialogHost.hidden) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(
      state.dialog.shadow.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])"
      )
    ).filter((element) => element.getClientRects().length > 0);
    if (!focusable.length) {
      event.preventDefault();
      state.dialog.panel.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && state.dialog.shadow.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && state.dialog.shadow.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function sendToBackground(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          reject(createMessageError(chrome.runtime.lastError.message, "extension_unavailable"));
          return;
        }
        if (!response || response.ok !== true) {
          const payload = response && response.error ? response.error : {};
          reject(createMessageError(payload.message || "MediaIndex 扩展后台无响应。", payload.code));
          return;
        }
        resolve(response.data);
      });
    });
  }

  function createMessageError(message, code) {
    const error = new Error(message);
    error.code = code || "unknown_error";
    return error;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
  }

  function providerName(provider) {
    const value = typeof provider === "string" ? provider.toLowerCase() : "";
    if (value.includes("quark") || value.includes("夸克")) {
      return "夸克";
    }
    if (value.includes("115")) {
      return "115";
    }
    return provider || "云盘分享";
  }

  function extensionVersionLabel() {
    try {
      const manifest = chrome.runtime.getManifest && chrome.runtime.getManifest();
      const version = manifest && (manifest.version_name || manifest.version);
      if (!version) {
        return "";
      }
      return " · " + (version.startsWith("v") ? version : "v" + version);
    } catch {
      return "";
    }
  }

  function normalizeText(text) {
    return text.replace(/\s+/g, " ").trim();
  }

  function isSupportedShareUrl(value) {
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
})();
