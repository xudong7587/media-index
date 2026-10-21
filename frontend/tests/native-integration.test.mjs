import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { Window } from "happy-dom";
import * as ui from "../src/components/native-ui.js";
import * as integrations from "../src/features/integrations/native-settings.js";
import * as downloads from "../src/features/integrations/native-download-settings.js";
import { OVERVIEW_HTML, WEBHOOK_CHAIN_HTML } from "../src/next/overview.js";
import * as diagnostics from "../src/features/settings/native-diagnostics.js";
import * as resources from "../src/features/discover/native-resources.js";
import * as mediaDetails from "../src/features/discover/native-media-detail.js";
import { workflowNodes } from "../src/features/transfer/native-workflow.js";
import * as directories from "../src/components/cloud/native-directory-picker.js";
import * as schedules from "../src/features/activity/native-schedules.js";
import * as webhooks from "../src/features/integrations/native-webhooks.js";
import * as covers from "../src/features/media-server/native-cover-studio.js";
import * as sessions from "../src/features/media-server/native-sessions.js";
import { GUIDE_HTML, bindNativeGuide } from "../src/next/guide.js";
import * as tracking from "../src/features/tracking/native-task-settings.js";
import * as jobs from "../src/features/activity/native-job-detail.js";
import * as taskPopover from "../src/features/activity/native-task-popover.js";
import * as strm from "../src/features/strm/native-status.js";
import * as cloud from "../src/features/cloud/native-connection-extras.js";
import { THEME_DATA } from "../src/next/theme-data.js";

const source = fs.readFileSync(new URL("../src/next/main.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?$/gm, "").replace(/\bboot\(\);\s*$/, "");
const configFixture = {
  enabled_providers: ["quark", "p115"], default_provider: "quark", version: "1.0.1",
  cloud_root: "/Library", qas_root: "/QAS", local_root: "/Local", category_paths: { movie: "电影" },
  quark_category_paths: {}, p115_category_paths: {}, notification_event_types: ["failure"],
  cloud_download_organizer_triggers: ["event"], cloud_download_organizer_mode: "copy",
  p115_staging_path: "/115Stage", quark_staging_path: "/QuarkStage",
  p115_cloud_download_organizer_directories: ["Films"], quark_cloud_download_organizer_directories: ["Films"],
  p115_strm_included_directories: ["/115/Films"], quark_strm_included_directories: ["/Quark/Films"],
  strm_video_extensions: ["mkv"], strm_excluded_name_tokens: [], strm_output_root: "/strm",
  p115_strm_source_root: "/115", quark_strm_source_root: "/Quark",
  quality_priority_keywords: [], resource_excluded_keywords: [],
  interaction_providers: ["p115"], interaction_shortcuts: ["status"],
  emby_cover_options: {}, emby_cover_library_options: {}, emby_cover_library_ids: [],
  emby_cover_style: "collage", emby_cover_refresh_hours: 24,
  cross_copy_transport: "openlist", openlist_qas_library_path: "/Quark", openlist_p115_library_path: "/115",
};
const media = { tmdb_id: 10, media_type: "movie", title: "测试电影", year: "2026", poster_url: "", vote_average: 8 };
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise((resolve) => setImmediate(resolve)); };

test("job detail reads persisted downstream nodes and keeps its expanded log across refresh", async (t) => {
  const job = { id: 20, tmdb_id: 10, media_type: "movie", provider: "p115", status: "done", stage: "provider_completed", message: "落盘完成" };
  const lane = { job_id: 20, provider: "p115", status: "done", steps: workflowNodes.map(([key, label]) => ({ key, label, status: key === "emby_refresh" ? "failed" : key === "openlist_sync" ? "skipped" : key === "resource_search" ? "running" : "done", message: `${label}的真实记录` })) };
  const { document, request } = setup(t, (call) => call.path === "/api/transfers/20" ? job : call.path === "/api/transfers/20/workflow" ? lane : undefined);
  await jobs.openNativeJobDetail(request, 20);
  assert.equal(document.querySelectorAll(".task-dialog .step").length, 8);
  assert.match(document.querySelector('[data-workflow-node="emby_refresh"].failed').textContent, /通知 Emby 入库的真实记录/);
  assert.match(document.querySelector('[data-workflow-node="resource_search"]').textContent, /未记录最终结果/);
  assert.equal(document.querySelector('[data-workflow-node="resource_search"].current'), null);
  document.querySelector("[data-job-show-log]").click();
  assert.equal(document.querySelector("[data-job-show-log]").textContent, "关闭完整记录");
  assert.equal(document.querySelector("[data-job-log]").hidden, false);
  document.querySelector("[data-job-refresh]").click(); await flush();
  assert.equal(document.querySelector("[data-job-log]").hidden, false);
  assert.equal(document.querySelector("[data-job-show-log]").getAttribute("aria-expanded"), "true");
  document.querySelector("[data-job-show-log]").click();
  assert.equal(document.querySelector("[data-job-show-log]").textContent, "查看完整记录");
});

test("media workbench keeps a healthy provider usable and freezes a single verified transfer", async (t) => {
  let finishTransfer;
  const { document, request, calls } = setup(t, (call) => {
    if (call.path.includes("/resources?")) {
      if (call.path.includes("provider=quark")) throw new Error("夸克查询失败");
      return { found: true, ready: true, share_url: "https://115.com/s/verified", message: "115 核对完成" };
    }
    if (call.path.includes("destination-options")) return [{ child_name: "Films", path: "/Cloud/Films" }];
    if (call.path.includes("/workflow/")) return { providers: [], steps: [] };
    if (call.path === "/api/transfers/batches") return new Promise((resolve) => { finishTransfer = resolve; });
  });
  await mediaDetails.openNativeMediaDetail(request, media);
  assert.equal(document.querySelectorAll(".md-provider").length, 2);
  assert.equal(document.querySelectorAll(".workflow-horizontal .step").length, 16);
  assert.match(document.querySelector(".md-providers").textContent, /夸克查询失败/);
  const button = document.querySelector('[data-md-provider-transfer="p115"]');
  assert.equal(button.textContent, "转存到115");
  button.click(); button.click(); await flush();
  const transfers = calls.filter((call) => call.path === "/api/transfers/batches");
  assert.equal(transfers.length, 1);
  assert.deepEqual(transfers[0].payload.items, [{ provider: "p115", openlist_fallback_to_p115: false, preferred_share_urls: ["https://115.com/s/verified"], preferred_share_only: true }]);
  assert.equal(calls.some((call) => call.path.includes("destination-options")), false);
  assert.equal(document.querySelector("[data-md-destination]"), null);
  assert.equal(document.querySelector("[data-md-category]").disabled, true);
  finishTransfer({ id: 50, ok: true }); await flush();
  assert.equal(button.disabled, true);
  assert.match(button.textContent, /已提交/);
});

test("manual media share identifies its provider and confirms direct library transfer without a staging directory", async (t) => {
  const { document, request, calls } = setup(t, (call) => {
    if (call.path.includes("/resources?")) return { found: false };
    if (call.path.includes("destination-options")) return [];
    if (call.path.includes("/workflow/")) return {};
    if (call.path === "/api/transfers/direct-link/options") return { link: call.payload.link, options: [{ path: "/Cloud/Films", category: "movie" }] };
  });
  await mediaDetails.openNativeMediaDetail(request, media);
  const input = document.querySelector("#mdManualLink"), form = document.querySelector(".md-manual");
  input.value = "https://115.com/s/first";
  form.dispatchEvent(new Event("submit", { cancelable: true })); await flush();
  assert.ok(document.querySelector("[data-md-manual-target] button"));
  assert.equal(calls.filter((call) => call.path === "/api/transfers/batches").length, 0);
  input.value = "https://115.com/s/second"; input.dispatchEvent(new Event("input"));
  assert.equal(document.querySelector("[data-md-manual-target] button"), null);
  form.dispatchEvent(new Event("submit", { cancelable: true })); await flush();
  document.querySelector("[data-md-manual-target] button").click(); await flush();
  const write = calls.find((call) => call.path === "/api/transfers/batches");
  assert.deepEqual(write.payload.items[0].preferred_share_urls, ["https://115.com/s/second"]);
  assert.equal(write.payload.items[0].provider, "p115");
  assert.equal("cloud_download_child" in write.payload.items[0], false);
  assert.equal(calls.some((call) => call.path.includes("direct-link")), false);
});

function setup(t, handler) {
  const window = new Window({ url: "http://localhost/" });
  window.document.body.innerHTML = '<div id="root"></div>';
  for (const key of ["window", "document", "location", "navigator", "HTMLInputElement", "Event", "FormData"]) Object.defineProperty(globalThis, key, { configurable: true, value: key === "window" ? window : window[key] });
  const calls = [];
  const config = structuredClone(configFixture);
  async function request(path, options = {}) {
    const payload = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
    const call = { path, method: options.method || "GET", payload };
    calls.push(call);
    if (handler) {
      const custom = await handler(call, config);
      if (custom !== undefined) return custom;
    }
    if (path === "/api/config/status" || path === "/api/cross-copy/config") return config;
    if (path === "/api/config") { Object.assign(config, payload); return { ok: true }; }
    if (path === "/api/diagnostics/support/status") return { enabled: false, active_token_count: 0 };
    if (path === "/api/webhooks/connections") return { items: [], event_types: ["transfer.completed"], inbound_actions: { providers: [] } };
    if (path.includes("deliveries/recent") || path.includes("/notifications")) return { items: [], unread_count: 0 };
    if (path.includes("/discover?") || path.includes("/search?")) return { results: [media] };
    if (path === "/api/media/movie/10") return media;
    if (path === "/api/integrations/emby/dashboard") return { server: { name: "测试媒体库" }, libraries: [{ id: "lib1", name: "电影" }], sessions: [], latest_items: [] };
    if (path.includes("/covers/fonts")) return { fonts: [{ id: "default", label: "默认" }] };
    if (path === "/api/openlist/tasks") return { tasks: [] };
    if (call.method === "GET") return [];
    return { ok: true, id: 42 };
  }
  const context = vm.createContext({
    ...ui, ...integrations, ...downloads, ...diagnostics, ...resources, ...mediaDetails, ...directories, ...schedules, ...webhooks, ...covers, ...sessions, ...tracking, ...jobs, ...taskPopover, ...strm, ...cloud,
    THEME_DATA, OVERVIEW_HTML, WEBHOOK_CHAIN_HTML, GUIDE_HTML, bindNativeGuide, QRCode: {},
    window, document: window.document, location: window.location, navigator: window.navigator,
    localStorage: window.localStorage, sessionStorage: window.sessionStorage,
    HTMLInputElement: window.HTMLInputElement, FormData: window.FormData,
    URL, URLSearchParams, Blob, console, setTimeout: window.setTimeout.bind(window),
    clearTimeout: window.clearTimeout.bind(window), confirm: () => true, alert: () => {},
    fetch: async (path, options) => {
      try { return new Response(JSON.stringify(await request(path, options)), { headers: { "Content-Type": "application/json" } }); }
      catch (error) { return new Response(JSON.stringify({ detail: error.message }), { status: 422 }); }
    },
  });
  vm.runInContext(source + `
    globalThis.app = {state, settingsState, wsState, subsState, strmState, crossState, discoverState,
      render, renderSettingsBody, bindSettings, loadSettings, saveSettings, wsRulesView, wsCloudView, wsWebhookView,
      bindWs, saveWsSection, strmProviderView, renderSubsBody, bindSubs, loadWs, loadStrm, bindRankInline,
      quickTrack, openDetail, parseDirectLink, runManualOrganize, bindLogin, loginView, api,
      runTrackingGroup, openChannelEditor, loadDiscover, bindAppearance, refreshAppearancePop, applyAppearance, runStrmJob, rescanStrm, openPansouImport};`, context);
  t.after(async () => { await window.happyDOM.abort(); window.close(); });
  return { window, document: window.document, app: context.app, calls, config, request };
}

test("shell drawer toggles accessibly, closes from its backdrop, and retains the version on navigation", async (t) => {
  const { app, document, window } = setup(t);
  app.state.config = structuredClone(configFixture);
  await app.render();
  const menu = document.querySelector("[data-menu]");
  assert.equal(document.querySelector(".side-foot [data-theme-toggle]"), null);
  assert.ok(document.querySelector('.side-foot a[href="https://github.com/xudong7587/media-index"]'));
  assert.equal(menu.getAttribute("aria-controls"), "sidebar");
  menu.click();
  assert.equal(document.querySelector(".app").classList.contains("menu-open"), true);
  assert.equal(menu.getAttribute("aria-expanded"), "true");
  assert.equal(menu.getAttribute("aria-label"), "关闭菜单");
  menu.click();
  assert.equal(menu.getAttribute("aria-expanded"), "false");
  menu.click();
  document.querySelector("[data-menu-close]").click();
  assert.equal(document.querySelector(".app").classList.contains("menu-open"), false);
  assert.equal(menu.getAttribute("aria-label"), "打开菜单");
  document.querySelector('#sidebar [data-route="strm"]').click();
  assert.equal(window.location.hash, "#strm");
  await app.render();
  assert.equal(document.querySelector('[data-route="strm"]').getAttribute("aria-current"), "page");
  assert.equal(document.querySelector("[data-menu]").getAttribute("aria-expanded"), "false");
  assert.equal(document.querySelector("#version").textContent, "MediaIndex v1.0.1");
});

test("media detail is a right-hand routed page with its sidebar available and return navigation", async (t) => {
  const { app, document, window } = setup(t, (call) => {
    if (call.path.includes("/resources?")) return { found: false };
    if (call.path.includes("/workflow/")) return { steps: [] };
  });
  await app.openDetail("movie", 10);
  assert.equal(window.location.hash, "#discover/movie/10");
  await app.render();
  assert.ok(document.querySelector("#sidebar [data-route=system]"));
  assert.ok(document.querySelector("#content > .media-detail-page"));
  assert.equal(document.querySelector("dialog"), null);
  assert.ok(document.querySelector('#sidebar [aria-current="page"][data-route="discover"]'));
  document.querySelector("[data-md-close]").click();
  assert.equal(window.location.hash, "#discover");
  await app.render();
  assert.equal(document.querySelector(".media-detail-page"), null);
  assert.ok(document.querySelector("#discoverPage"));
});

test("compact workflow nodes disclose details on click and retain the selection after polling refresh", async (t) => {
  const message = "后端保存的完整原因：无法确认目标文件，等待人工核对";
  const { document, request } = setup(t, (call) => {
    if (call.path.includes("/resources?")) return { found: false };
    if (call.path.includes("/workflow/")) return { job_id: 77, provider: "p115", status: "failed", steps: workflowNodes.map(([key]) => ({ key, status: "failed", message, updated_at: "2026-10-21 04:00:00" })) };
  });
  const page = await mediaDetails.openNativeMediaDetail(request, media);
  const nodeSelector = '[data-workflow-lane="p115:77:0"] [data-workflow-node="transfer"]';
  const node = document.querySelector(nodeSelector);
  assert.equal(node.tagName, "BUTTON");
  assert.doesNotMatch(node.textContent, /后端保存的完整原因/);
  assert.equal(document.querySelector(".workflow-node-detail").hidden, true);
  node.click();
  assert.equal(node.getAttribute("aria-expanded"), "true");
  assert.match(document.querySelector(".workflow-node-detail").textContent, /后端保存的完整原因/);
  document.querySelector("[data-md-workflow-refresh]").click(); await flush();
  assert.equal(document.querySelector(nodeSelector).getAttribute("aria-expanded"), "true");
  assert.equal(document.querySelector(".workflow-node-detail").hidden, false);
  document.querySelector("[data-node-close]").focus();
  document.querySelector("[data-md-workflow-refresh]").click(); await flush();
  assert.equal(document.activeElement, document.querySelector("[data-node-close]"));
  document.querySelector("[data-node-close]").click();
  assert.equal(document.querySelector(".workflow-node-detail").hidden, true);
  assert.equal(document.querySelector(nodeSelector).getAttribute("aria-expanded"), "false");
  page.dispose(); page.remove();
});

test("115 candidate selection stays mounted while the other provider resolves and submits only that provider", async (t) => {
  let resolveOther;
  const { document, request, calls } = setup(t, (call) => {
    if (call.path.includes("/resources?")) {
      if (call.path.includes("provider=quark")) return new Promise((resolve) => { resolveOther = resolve; });
      return { found: true, requires_review: true, candidates: [{ title: "115候选", cloud_type: "115", share_url: "https://115.com/s/chosen" }] };
    }
    if (call.path.includes("/workflow/")) return { steps: [] };
  });
  const mounted = mediaDetails.openNativeMediaDetail(request, media);
  await flush();
  const choice = document.querySelector('[data-md-candidate="p115:0"]');
  choice.value = "0"; choice.dispatchEvent(new Event("change")); choice.focus();
  assert.equal(document.querySelector('[data-md-provider-transfer="p115"]').disabled, false);
  resolveOther({ found: false }); await mounted;
  assert.equal(document.querySelector('[data-md-candidate="p115:0"]'), choice);
  assert.equal(document.activeElement, choice);
  document.querySelector('[data-md-provider-transfer="p115"]').click(); await flush();
  const item = calls.find((call) => call.path === "/api/transfers/batches").payload.items[0];
  assert.equal(item.provider, "p115");
  assert.deepEqual(item.preferred_share_urls, ["https://115.com/s/chosen"]);
  assert.equal("cloud_download_child" in item, false);
});

test("combined transfer uses both ready providers, and selected 115 candidates retain their share actions", async (t) => {
  const copied = [];
  const { document, request, calls, window } = setup(t, (call, config) => {
    config.pansou_url = "https://pansou.example.test/";
    if (call.path.includes("/resources?")) return call.path.includes("provider=p115")
      ? { found: true, requires_review: true, candidates: [{ title: "115人工候选", cloud_type: "115", share_url: "https://115.com/s/selected", password: "1234" }] }
      : { ready: true, found: true, share_url: "https://pan.quark.cn/s/ready" };
    if (call.path.includes("/workflow/")) return {};
  });
  Object.defineProperty(window.navigator, "clipboard", { value: { writeText: async (text) => copied.push(text) }, configurable: true });
  await mediaDetails.openNativeMediaDetail(request, media);
  assert.equal(document.querySelector("[data-md-transfer]").disabled, true);
  const select = document.querySelector('[data-md-candidate="p115:0"]');
  select.value = "0"; select.dispatchEvent(new Event("change"));
  assert.equal(document.querySelector('[data-md-provider-transfer="p115"]').textContent, "转存到115");
  assert.equal(document.querySelector('[data-md-provider-transfer="quark"]').textContent, "转存到夸克");
  const links = document.querySelector('[data-md-provider="p115"] .md-resource-links');
  assert.equal(links.querySelector("a").href, "https://115.com/s/selected");
  assert.ok([...links.querySelectorAll("a")].some((a) => a.href === "https://pansou.example.test/"));
  links.querySelector("button").click(); await flush();
  assert.deepEqual(copied, ["https://115.com/s/selected 提取码：1234"]);
  assert.match(document.querySelector(".md-copy-notice").textContent, /115分享链接已复制/);
  assert.equal(document.querySelector("[data-md-output]").textContent, "");
  await new Promise((resolve) => setTimeout(resolve, 1900));
  assert.equal(document.querySelector(".md-copy-notice"), null);
  window.navigator.clipboard.writeText = async () => { throw new Error("剪贴板不可用"); };
  links.querySelector("button").click(); await flush();
  assert.equal(document.querySelector(".md-copy-notice.error").textContent, "剪贴板不可用");
  assert.equal(document.querySelector("[data-md-output]").textContent, "");
  document.querySelector("[data-md-transfer]").click(); await flush();
  const payload = calls.find((call) => call.path === "/api/transfers/batches").payload;
  assert.deepEqual(payload.items.map((item) => item.provider).sort(), ["p115", "quark"]);
  assert.ok(payload.items.every((item) => !Object.hasOwn(item, "cloud_download_child")));
});

test("only confirmed absence on 115 offers Quark then CD2 sync, without a second 115 transfer", async (t) => {
  const { document, request, calls } = setup(t, (call, config) => {
    Object.assign(config, { cross_copy_transport: "cd2", cd2_url: "https://cd2.example.invalid", openlist_enabled: true, has_cd2_token: true, cd2_qas_library_path: "/Quark", cd2_p115_library_path: "/115" });
    if (call.path.includes("/resources?")) return call.path.includes("provider=p115") ? { found: false, candidate_count: 0 } : { ready: true, found: true, share_url: "https://pan.quark.cn/s/ready" };
    if (call.path.includes("/workflow/")) return {};
  });
  await mediaDetails.openNativeMediaDetail(request, media);
  const button = document.querySelector("[data-md-transfer]");
  assert.equal(button.textContent, "先存夸克，再同步到115");
  assert.equal(button.disabled, false);
  button.click(); button.click(); await flush();
  const writes = calls.filter((call) => call.path === "/api/transfers/batches");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].payload.items.length, 1);
  assert.equal(writes[0].payload.items[0].provider, "quark");
  assert.equal(writes[0].payload.items[0].openlist_fallback_to_p115, true);
});

test("guide opens all nine real chapters and its four shortcut cards", async (t) => {
  const { app, document, window, calls } = setup(t);
  window.location.hash = "guide"; await app.render();
  for (const control of document.querySelectorAll("#guideToc button")) {
    control.click();
    const shown = [...document.querySelectorAll("article.chapter")].filter((node) => !node.hidden);
    assert.equal(shown.length, 1);
    assert.equal(shown[0].dataset.chapter, control.dataset.chapter);
    assert.equal(control.getAttribute("aria-pressed"), "true");
  }
  for (const card of document.querySelectorAll("[data-guide-chapter]")) {
    card.click();
    assert.equal(document.querySelector("article.chapter:not([hidden])").dataset.chapter, card.dataset.guideChapter);
  }
  assert.equal(calls.some((call) => call.method !== "GET"), false);
});

test("channel bulk toggles preserve rules and report partial failure without syncing channels", async (t) => {
  const channels = [1, 2].map((id) => ({ id, channel_id: `channel${id}`, enabled: false, positive_keywords: ["保留"], auto_transfer: false }));
  const { app, document, window, calls, config } = setup(t, (call) => {
    if (call.path === "/api/cloud/channels" && call.method === "GET") return channels;
    if (call.path === "/api/cloud/channels" && call.method === "PUT") {
      if (call.payload.channel_id === "channel2" && call.payload.enabled) throw new Error("频道二保存失败");
      Object.assign(channels.find((item) => item.channel_id === call.payload.channel_id), call.payload); return { ok: true };
    }
  });
  config.pansou_exclude_keywords = "预告,花絮,\n原有关键词,<保留>";
  app.wsState.section = "sources"; window.location.hash = "workspace"; await app.render(); await flush();
  document.querySelector('[data-channel-all="true"]').click(); await flush();
  assert.match(document.querySelector("#wsChannels").textContent, /1 个失败.*频道二保存失败/);
  assert.equal(channels[0].enabled, true); assert.equal(channels[1].enabled, false);
  document.querySelector('[data-channel-all="false"]').click(); await flush();
  assert.equal(channels[0].enabled, false);
  const writes = calls.filter((call) => call.path === "/api/cloud/channels" && call.method === "PUT");
  assert.equal(writes.length, 3);
  assert.ok(writes.every((call) => call.payload.positive_keywords[0] === "保留" && call.payload.auto_transfer === false));
  assert.equal(calls.some((call) => call.path.includes("/channels/sync")), false);
  const keywords = document.querySelector("#wsPansouExclude");
  assert.equal(keywords.tagName, "TEXTAREA");
  assert.equal(keywords.value, config.pansou_exclude_keywords);
  keywords.value += ",新增关键词";
  document.querySelector('[data-ws-save="sources"]').click(); await flush();
  const saved = calls.find((call) => call.path === "/api/config" && call.method === "PUT");
  assert.equal(saved.payload.pansou_exclude_keywords, "预告,花絮,\n原有关键词,<保留>,新增关键词");
});

test("manual copy exposes reverse direction for saved CD2 only and resets selection when switched", async (t) => {
  let cd2 = true;
  const { app, document, window, calls } = setup(t, (call, config) => {
    if (call.path === "/api/cross-copy/config") return { ...config, cross_copy_transport: cd2 ? "cd2" : "openlist", cd2_qas_library_path: "/CD2/Quark", cd2_p115_library_path: "/CD2/115" };
    if (call.path === "/api/openlist/entries") return { entries: [{ name: "Show.mkv", is_dir: false }] };
  });
  app.crossState.tab = "manual"; window.location.hash = "cross-cloud"; await app.render();
  const direction = document.querySelector("[data-copy-direction]");
  direction.value = "p115_to_quark"; direction.dispatchEvent(new Event("change")); await flush();
  assert.equal(app.crossState.source, "/CD2/115"); assert.equal(app.crossState.target, "/CD2/Quark");
  document.querySelector('[data-copy-pick][data-side="source"]').click();
  document.querySelector("[data-copy-run]").click(); await flush();
  const write = calls.find((call) => call.path === "/api/openlist/sync-selected");
  assert.equal(write.payload.source_dir, "/CD2/115"); assert.equal(write.payload.target_dir, "/CD2/Quark");
  cd2 = false; await app.render();
  assert.equal(document.querySelector("[data-copy-direction]"), null);
  assert.equal(app.crossState.direction, "quark_to_p115");
  assert.equal(app.crossState.source, "/Quark");
});

test("media libraries occupy their row and the session summary opens a separate refreshable window", async (t) => {
  let refresh = false;
  const { app, document, window, calls } = setup(t, (call, config) => {
    config.has_emby_api_key = true;
    if (call.path === "/api/integrations/emby/dashboard") return { server: { name: "Emby" }, libraries: [{ id: "l1", name: "电影" }], latest_items: [], sessions: refresh ? [] : [{ user_name: "测试用户", device_name: "电视", item_name: "正在看", is_playing: true }] };
  });
  window.location.hash = "media-server"; await app.render();
  assert.equal(document.querySelectorAll(".media-library-row>section").length, 1);
  assert.equal(document.querySelector(".media-library-row").textContent.includes("正在看"), false);
  document.querySelector("[data-open-sessions]").click();
  assert.match(document.querySelector(".media-sessions-dialog").textContent, /正在看/);
  refresh = true; document.querySelector("[data-sessions-refresh]").click(); await flush();
  assert.match(document.querySelector(".media-sessions-dialog").textContent, /当前没有播放会话/);
  assert.equal(calls.some((call) => call.method !== "GET"), false);
});

test("STRM tabs keep provider directory controls and prevent concurrent manual submissions", async (t) => {
  let finishJob;
  const { app, document, window, calls } = setup(t, (call) => {
    if (call.path === "/api/cloud/strm/jobs") return new Promise((resolve) => { finishJob = resolve; });
    if (call.path.startsWith("/api/cloud/quark/directory?")) return [{ name: "媒体库", file_id: "q1", is_dir: true }];
  });
  window.location.hash = "strm"; await app.render();
  assert.ok(document.querySelector('[data-directory-for="strmOutput"]'));
  assert.ok(document.querySelector('[data-directory-for="strmEmbyRoot"]'));
  document.querySelector('[data-strm-section="p115"]').click(); await flush();
  for (const id of ["strmRoot", "strmInclude", "strmActionDir", "strmLifePath"]) assert.ok(document.querySelector(`[data-directory-for="${id}"]`));
  document.querySelector("#strmActionDir").value = "/115/Films";
  document.querySelector("[data-strm-run]").click();
  document.querySelector("[data-strm-run]").click();
  document.querySelector("[data-strm-rescan]").click(); await flush();
  assert.equal(calls.filter((call) => call.path === "/api/cloud/strm/jobs").length, 1);
  assert.equal(calls.filter((call) => call.path === "/api/strm/directory-rescan").length, 0);
  assert.equal(document.querySelector("[data-strm-run]").getAttribute("aria-busy"), "true");
  finishJob({ ok: true, message: "已提交" }); await flush();
  assert.equal(document.querySelector("[data-strm-run]").disabled, false);
  document.querySelector('[data-strm-section="quark"]').click(); await flush();
  assert.equal(document.querySelector("#strmLifePath"), null);
  assert.ok(document.querySelector('[data-directory-for="strmInclude"]'));
  document.querySelector('[data-directory-for="strmRoot"]').click(); await flush();
  assert.ok(calls.some((call) => call.path.startsWith("/api/cloud/quark/directory?")));
  document.querySelector("[data-dir-open]").click(); await flush();
  document.querySelector("[data-dir-choose]").click();
  assert.equal(document.querySelector("#strmRoot").value, "/媒体库");
});
function uniqueIds(document) {
  const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
  assert.equal(ids.length, new Set(ids).size, "rendered controls must have unique IDs");
}
function lastWrite(calls, path = "/api/config") {
  return calls.filter((call) => call.path === path && call.method !== "GET").at(-1)?.payload;
}

test("all eight routes mount without runtime failures or duplicate controls", async (t) => {
  const { app, window, document } = setup(t);
  for (const route of ["discover", "subscriptions", "workspace", "cross-cloud", "strm", "media-server", "system", "guide"]) {
    window.location.hash = route;
    await app.render();
    await flush();
    assert.ok(document.querySelector("main"), route);
    uniqueIds(document);
  }
});

test("settings tabs and workspace sections bind once; switch changes once and saves once", async (t) => {
  const { app, window, document, calls } = setup(t);
  window.location.hash = "system";
  await app.render();
  app.settingsState.tab = "notifications";
  app.renderSettingsBody();
  app.bindSettings();
  app.bindSettings();
  uniqueIds(document);
  const toggle = document.querySelector("#setPushEnabled");
  toggle.click();
  assert.equal(toggle.getAttribute("aria-checked"), "true");
  const before = calls.filter((c) => c.method === "PUT").length;
  document.querySelector('[data-settings-save="notifications"]').click();
  await flush();
  assert.equal(calls.filter((c) => c.method === "PUT").length - before, 1);
  assert.equal(lastWrite(calls).notification_external_enabled, true);
});

test("general and Telegram forms send backend field names and preserve blank secrets", async (t) => {
  const { app, window, document, calls } = setup(t);
  window.location.hash = "system"; await app.render();
  app.settingsState.tab = "basic"; app.renderSettingsBody();
  document.querySelector("#setCloudRoot").value = "/Changed";
  await app.saveSettings("basic");
  assert.equal(lastWrite(calls).cloud_save_path, "/Changed");
  assert.equal(lastWrite(calls).qas_save_path, "/QAS");
  assert.equal(lastWrite(calls).local_save_path, "/Local");
  assert.ok(!("cloud_root" in lastWrite(calls)));
  assert.ok(!("tmdb_api_key" in lastWrite(calls)));
  app.settingsState.tab = "notifications"; app.renderSettingsBody();
  document.querySelector("#setTelegramToken").value = "dummy-test-token";
  document.querySelector("#setTelegramEnabled").click();
  await app.saveSettings("telegram");
  assert.equal(lastWrite(calls).telegram_bot_token, "dummy-test-token");
  assert.equal(lastWrite(calls).telegram_enabled, true);
  assert.ok(!("telegram_token" in lastWrite(calls)));
});

test("MDC and category forms save visible inputs; organizer uses scheduled without clearing staging", async (t) => {
  const { app, window, document, calls } = setup(t);
  window.location.hash = "workspace"; await app.render();
  app.wsState.section = "webhook"; await app.loadWs();
  document.querySelector("#wsWebhookEnabled").click();
  document.querySelector("#wsWebhookRoot").value = "/Configured";
  await app.saveWsSection("webhook");
  assert.equal(lastWrite(calls).mdc_webhook_enabled, true);
  assert.equal(lastWrite(calls).mdc_webhook_root_path, "/Configured");
  app.wsState.section = "rules"; await app.loadWs();
  const category = document.querySelector('[data-cat^="base:"]');
  category.value = "新分类";
  await app.saveWsSection("rules");
  assert.equal(lastWrite(calls).category_paths[category.dataset.cat.split(":")[1]], "新分类");
  app.wsState.section = "cloud-download"; await app.loadWs();
  document.querySelector('[data-cloud-trigger="scheduled"]').click();
  await app.saveWsSection("cloud");
  assert.deepEqual(lastWrite(calls).cloud_download_organizer_triggers, ["event", "scheduled"]);
  assert.ok(!("p115_staging_path" in lastWrite(calls)));
  assert.ok(!("quark_staging_path" in lastWrite(calls)));
});

test("episode reads and fill requests use the selected provider state identity", async (t) => {
  const task = { id: 11, title: "追更样本", status: "active", media_type: "tv", provider_states: [
    { id: 11, provider: "quark", status: "active" }, { id: 22, provider: "p115", status: "active" },
  ] };
  const { app, document, window, calls } = setup(t, (call) => {
    if (call.path === "/api/tracking") return [task];
    if (call.path.endsWith("/episodes")) return { episodes: [{ episode_number: 2, aired: true, status: "missing" }] };
  });
  window.location.hash = "subscriptions"; await app.render();
  document.querySelector('[data-episodes="22"]').click(); await flush();
  assert.ok(calls.some((call) => call.path === "/api/tracking/22/episodes"));
  document.querySelector("[data-ep-pick]").click();
  document.querySelector("[data-ep-fill]").click(); await flush();
  assert.deepEqual(lastWrite(calls, "/api/tracking/22/fill"), { episode_numbers: [2] });
  assert.ok(!calls.some((call) => call.path === "/api/tracking/11/fill"));
});

test("movie resources submit the selected candidate once to the formal library without a staging selector", async (t) => {
  const { request, calls, document } = setup(t, (call) => {
    if (call.path.includes("/resources?")) return { found: true, ready: false, requires_review: true, candidates: [{ title: "候选 A", share_url: "https://pan.quark.cn/s/test", provider: "quark" }] };
    if (call.path.includes("destination-options")) return [{ provider: "quark", child_name: "Films", path: "/Downloads/Films" }];
  });
  await resources.openResourceSearch(request, media);
  const button = document.querySelector("[data-resource-submit]");
  assert.equal(button.disabled, true);
  document.querySelector('[name="resourceCandidate"]').click();
  assert.equal(button.disabled, false);
  button.click(); button.click(); await flush();
  const writes = calls.filter((call) => call.path === "/api/transfers/batches");
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0].payload.items[0].preferred_share_urls, ["https://pan.quark.cn/s/test"]);
  assert.equal("cloud_download_child" in writes[0].payload.items[0], false);
  assert.equal(document.querySelector("#resourceDestination"), null);
  assert.equal(calls.some((call) => call.path.includes("destination-options")), false);
  assert.equal(writes[0].payload.items[0].preferred_share_only, true);
});

test("directory failure is visible and never accepted as an empty authorized folder", async (t) => {
  const { request, document } = setup(t, (call) => { if (call.path.includes("/directory?")) throw new Error("网盘凭据已失效"); });
  let chosen = false;
  await directories.pickNativeDirectory(request, "p115", () => { chosen = true; });
  assert.match(document.body.textContent, /网盘凭据已失效/);
  assert.equal(document.querySelector("[data-dir-choose]"), null);
  assert.equal(chosen, false);
});

test("review selection requires nonempty files and submits only selected files", async (t) => {
  const { request, document, calls } = setup(t);
  tracking.openReviewSelection(request, { id: 3, job_id: 9, files: ["a.mkv", "b.mkv"], reasons: ["需核对年份"] }, async () => {});
  document.querySelector('[data-review-file="1"]').checked = false;
  document.querySelector("[data-review-submit]").click(); await flush();
  assert.deepEqual(lastWrite(calls, "/api/review/3/confirm"), { selected_files: ["a.mkv"] });
});

test("cover studio preserves per-library titles and sends actual render options", async (t) => {
  const { request, document, calls } = setup(t);
  await covers.openNativeCoverStudio(request, [{ id: "lib1", name: "电影" }], async () => {});
  document.querySelector('[data-config-field="zh_title"]').value = "电影时光";
  document.querySelector('[data-config-field="resolution"]').value = "720p";
  document.querySelector("[data-studio-save]").click(); await flush();
  const payload = lastWrite(calls);
  assert.equal(payload.emby_cover_options.resolution, "720p");
  assert.equal(payload.emby_cover_library_options.lib1.zh_title, "电影时光");
  document.querySelector("[data-studio-apply]").click(); await flush();
  assert.equal(lastWrite(calls, "/api/integrations/emby/libraries/lib1/cover").options.zh_title, "电影时光");
});

test("unknown endpoint failures stay visible in manual organizer controls", async (t) => {
  const { app, document, window } = setup(t, (call) => { if (call.path.endsWith("/organize")) throw new Error("目录不在已授权范围"); });
  window.location.hash = "workspace"; await app.render();
  app.wsState.section = "cloud-download"; await app.loadWs();
  document.querySelector("#organizePath").value = "/NotAuthorized/Movie";
  await app.runManualOrganize();
  assert.match(document.querySelector("#organizeResult").textContent, /目录不在已授权范围/);
});

test("group actions preserve provider success and report the failing provider", async (t) => {
  const { app, calls } = setup(t, (call) => {
    if (call.path === "/api/tracking/22/run") throw new Error("凭据失效");
  });
  app.subsState.tasks = [{ id: 11, provider_states: [{ id: 11, provider: "quark", status: "active" }, { id: 22, provider: "p115", status: "active" }] }];
  await assert.rejects(app.runTrackingGroup(11, "run"), /成功 1 \/ 2；115：凭据失效/);
  assert.ok(calls.some((call) => call.path === "/api/tracking/11/run"));
  await app.runTrackingGroup(11, "sync-storage");
  assert.ok(calls.some((call) => call.path === "/api/tracking/22/sync-storage"));
  assert.ok(!calls.some((call) => call.path === "/api/tracking/11/sync-storage"));
});

test("channel save failure keeps edited values and the dialog open", async (t) => {
  const { app, document, calls } = setup(t, (call) => {
    if (call.path === "/api/cloud/channels" && call.method === "PUT") throw new Error("频道保存失败");
  });
  app.openChannelEditor({ channel_id: "test", enabled: true });
  document.querySelector("#chName").value = "待保存名称";
  const button = document.querySelector("[data-editor-save]");
  button.click(); button.click(); await flush();
  assert.equal(calls.filter((call) => call.method === "PUT").length, 1);
  assert.equal(document.querySelector("#chName").value, "待保存名称");
  assert.equal(document.querySelector("dialog").open, true);
  assert.match(document.querySelector("[data-channel-error]").textContent, /频道保存失败/);
});

test("all settings and workspace sections render without duplicate input identifiers", async (t) => {
  const { app, document, window } = setup(t);
  window.location.hash = "settings"; await app.render();
  for (const tab of [...document.querySelectorAll("[data-settings-tab]")].map((node) => node.dataset.settingsTab)) {
    document.querySelector(`[data-settings-tab="${tab}"]`).click(); await flush();
    uniqueIds(document);
    assert.ok(document.querySelector("#settingsBody").textContent.trim());
  }
  window.location.hash = "workspace"; await app.render();
  for (const section of [...document.querySelectorAll("[data-ws-section]")].map((node) => node.dataset.wsSection)) {
    app.wsState.section = section; await app.loadWs();
    uniqueIds(document);
  }
});

test("schedule editors persist their documented fields and never run jobs on open", async (t) => {
  const { request, document, calls, config } = setup(t);
  for (const definition of schedules.scheduleDefinitions) {
    for (const [key, , type] of definition.fields) {
      if (config[key] === undefined) config[key] = type === "number" ? 10 : type === "boolean" ? false : type === "time" ? "09:00" : "";
    }
  }
  for (let index = 0; index < schedules.scheduleDefinitions.length; index++) {
    await schedules.editSchedule(request, index, async () => {});
    const button = document.querySelector("[data-schedule-save]");
    assert.ok(button);
    button.click(); await flush();
    const payload = lastWrite(calls);
    for (const [key] of schedules.scheduleDefinitions[index].fields) assert.ok(Object.hasOwn(payload, key), key);
    document.querySelector("dialog").close();
  }
  assert.equal(calls.filter((call) => call.method === "POST").length, 0);
});

test("template task popover opens real jobs and shows all eight pipeline nodes", async (t) => {
  const job = { id: 17, display_title: "测试剧集", provider: "quark", status: "running", stage: "provider_submitting", message: "正在提交", created_at: "2026-10-20 12:00:00" };
  const { app, document, calls, window } = setup(t, (call) => {
    if (call.path === "/api/transfers") return [job];
    if (call.path === "/api/transfers/17") return job;
  });
  window.location.hash = "workspace"; await app.render(); await flush();
  document.querySelector("#btnTasks").click(); await flush();
  assert.ok(document.querySelector("#activityPop.popover.open"));
  assert.equal(document.querySelectorAll(".pop-tab").length, 3);
  assert.equal(document.querySelector(".pop-pct"), null);
  document.querySelector('[data-task-detail="17"]').click(); await flush();
  assert.equal(document.querySelectorAll(".task-dialog .step").length, 8);
  assert.match(document.querySelector(".step.current").textContent, /提交网盘.*正在提交/);
  assert.equal(document.querySelectorAll(".step.done").length, 0);
  assert.ok(calls.some((call) => call.path === "/api/transfers/17"));
  assert.equal(calls.filter((call) => call.method !== "GET").length, 0);
  document.querySelector("[data-job-done]").click();
});


test("appearance remains operable after several material changes and offers six radius stops", async (t) => {
  const { app, document, window } = setup(t);
  window.location.hash = "system"; await app.render();
  document.querySelector("#btnAppearance").click();
  for (const material of ["clay", "metal", "soft"]) {
    const button = document.querySelector(`[data-material-value="${material}"]`) || document.querySelector("[data-material-value]");
    button.click();
  }
  const range = document.querySelector("#cornerRange");
  assert.equal(range.max, "5");
  range.value = "4"; range.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert.equal(document.documentElement.style.getPropertyValue("--ui-radius"), "22px");
  assert.equal(document.documentElement.style.getPropertyValue("--mat-radius"), "22px");
  document.querySelector("[data-appearance-close]").click();
  document.querySelector("#btnAppearance").click();
  assert.ok(document.querySelector("#appearancePop.open"));
  document.querySelector("#btnAppearance").click();
  assert.equal(document.querySelector("#appearancePop.open"), null);
});

test("legacy notification groups keep callback with WeCom and direct download out of general settings", async (t) => {
  const { app, document, window, calls } = setup(t);
  window.location.hash = "system"; await app.render();
  app.settingsState.tab = "basic"; app.renderSettingsBody();
  assert.equal(document.querySelector("#setTrackingScheduler"), null);
  assert.equal(document.querySelector("#setDirectPath"), null);
  app.settingsState.tab = "notifications"; app.renderSettingsBody();
  assert.equal(document.querySelectorAll("[data-notification-tab]").length, 3);
  assert.ok(document.querySelector("#wecomApplication #extra-wecom_callback_url"));
  document.querySelector("#extra-wecom_callback_url").value = "https://test.invalid/callback";
  await app.saveSettings("wecom_app");
  assert.equal(lastWrite(calls).wecom_callback_url, "https://test.invalid/callback");
  assert.ok(!Object.hasOwn(lastWrite(calls), "wecom_callback_token"));
  document.querySelector('[data-notification-tab="interaction"]').click();
  assert.ok(document.querySelector("[data-interaction-settings]"));
  assert.equal(document.querySelector("#setTelegramToken"), null);
  document.querySelector('[data-notification-tab="download"]').click(); await flush();
  assert.ok(document.querySelector("#setDirectPath + [data-directory-for]"));
  assert.match(document.body.textContent, /云下载路由/);
  assert.ok(document.querySelector("[data-interaction-records]"));
  uniqueIds(document);
});

test("TG import result stays in its source section and category paths are shared", async (t) => {
  const { app, document, window, calls } = setup(t);
  window.location.hash = "workspace"; await app.render();
  app.wsState.result = { ok: true, message: "已导入 3 个频道" };
  app.wsState.resultSection = "sources";
  app.wsState.section = "cloud-download"; await app.loadWs();
  assert.doesNotMatch(document.querySelector("#wsBody").textContent, /已导入 3/);
  assert.ok(document.querySelector("#organizePath").closest(".directory-input"));
  app.wsState.section = "rules"; await app.loadWs();
  assert.equal(document.querySelector('[data-cat^="p115:"]'), null);
  assert.equal(document.querySelector('[data-cat^="quark:"]'), null);
  await app.saveWsSection("rules");
  assert.deepEqual(lastWrite(calls).p115_category_paths, {});
  assert.deepEqual(lastWrite(calls).quark_category_paths, {});
});

test("STRM full-scope generation and a specific directory rescan use separate inputs", async (t) => {
  const { app, document, window, calls } = setup(t);
  window.location.hash = "strm"; await app.render();
  app.strmState.section = "p115"; await app.loadStrm();
  const modeRow = document.querySelector("#strmMode").closest(".manual-action-row");
  assert.ok(modeRow.querySelector("[data-strm-run]"));
  assert.equal(modeRow.querySelector("#strmActionDir"), null);
  document.querySelector("#strmMode").value = "full";
  document.querySelector("#strmActionDir").value = "/115/OneFilm";
  await app.runStrmJob("p115");
  assert.equal(lastWrite(calls, "/api/cloud/strm/jobs").root_path, "/115");
  assert.equal(lastWrite(calls, "/api/cloud/strm/jobs").mode, "full");
  await app.rescanStrm("p115");
  assert.equal(lastWrite(calls, "/api/strm/directory-rescan").directory_path, "/115/OneFilm");
});


test("channel import feedback stays beside channel actions and clears when its source is disabled", async (t) => {
  const { app, document, window } = setup(t, call => {
    if (call.path === "/api/cloud/channels/pansou") return { candidates: [{ channel_id: "test-channel", display_name: "测试频道" }] };
    if (call.path === "/api/cloud/channels/import-pansou") return { ok: true, message: "已导入 1 个频道" };
  });
  window.location.hash = "workspace"; await app.render();
  app.wsState.section = "sources"; await app.loadWs(); await flush();
  await app.openPansouImport();
  document.querySelector("[data-import-id]").checked = true;
  document.querySelector("[data-import-confirm]").click(); await flush();
  assert.match(document.querySelector("#wsChannels .row-actions").textContent, /已导入 1/);
  assert.equal([...document.querySelectorAll("#wsBody .inline-result")].filter(node => node.textContent.includes("已导入 1")).length, 1);
  await app.saveWsSection("telegram"); await flush();
  assert.doesNotMatch(document.querySelector("#wsBody").textContent, /已导入 1/);
});


test("platform changes stay inside discovery while loading and carousel navigation preserves the page", async (t) => {
  let slow = false;
  const gates = [];
  const items = [{ ...media, backdrop_url: "/poster-a.jpg" }, { ...media, tmdb_id: 11, title: "另一部电影", backdrop_url: "/poster-b.jpg" }];
  const { app, document, window } = setup(t, async call => {
    if (call.path.includes("/discover?")) {
      if (slow) await new Promise(resolve => gates.push(resolve));
      return { results: items };
    }
  });
  window.location.hash = "discover"; await app.render(); await flush();
  const rail = document.querySelector('[data-rail="hot"]');
  const hero = document.querySelector("#hero");
  const platform = document.querySelector('section.ranking [data-platform]:not([aria-selected="true"])');
  const nextPlatform = platform.dataset.platform;
  slow = true;
  platform.click(); await flush();
  assert.equal(app.discoverState.section, "explore");
  assert.equal(document.querySelector("section.ranking").getAttribute("aria-busy"), "true");
  assert.equal(document.querySelector(`section.ranking [data-platform="${nextPlatform}"]`).getAttribute("aria-selected"), "true");
  assert.equal(document.querySelector('[data-rail="hot"]'), rail);
  assert.equal(document.querySelector("#hero"), hero);
  assert.ok(document.querySelector("section.ranking"));
  assert.equal(document.querySelector(".ranking-hero"), null);
  document.querySelector('[data-hero="1"]').click();
  assert.equal(document.querySelector('[data-rail="hot"]'), rail);
  assert.equal(document.querySelector("#hero"), hero);
  slow = false; gates.forEach(resolve => resolve()); await flush();
  assert.equal(document.querySelector('[data-rail="hot"]'), rail);
  assert.equal(document.querySelector(`section.ranking [data-platform="${nextPlatform}"]`).getAttribute("aria-selected"), "true");
  assert.equal(window.location.hash, "#discover");
});
