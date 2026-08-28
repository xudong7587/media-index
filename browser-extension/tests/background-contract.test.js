"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const shareUrl = "https://pan.quark.cn/s/demo";
const requests = [];
let messageListener;
let backendContract = 2;

global.chrome = {
  runtime: {
    id: "mediaindex-test-extension",
    onInstalled: { addListener() {} },
    onMessage: {
      addListener(listener) {
        messageListener = listener;
      }
    },
    async openOptionsPage() {}
  },
  storage: {
    local: {
      async setAccessLevel() {},
      async get() {
        return { baseUrl: "https://mediaindex.test", username: "sunny" };
      },
      async set() {},
      async remove() {}
    }
  },
  permissions: {
    async contains() {
      return true;
    },
    async remove() {
      return true;
    }
  }
};

global.fetch = async (url, init) => {
  const body = init.body ? JSON.parse(init.body) : undefined;
  requests.push({ url, init, body });
  let payload = {};
  if (url.endsWith("/api/transfers/direct-link/options")) {
    payload = {
      direct_link_contract_version: backendContract,
      provider: "quark",
      root_path: "/夸克媒体/云下载",
      cloud_download_enabled: false,
      options: []
    };
  } else if (url.endsWith("/api/transfers/direct-link/rename-preview")) {
    payload = {
      direct_link_contract_version: 2,
      save_path: "/夸克媒体/03电视剧/花开锦绣 (2026)/Season 1",
      files: []
    };
  } else if (url.endsWith("/api/transfers/direct-link")) {
    payload = { ok: true, direct_link_contract_version: 2 };
  }
  return {
    ok: true,
    status: 200,
    async text() {
      return JSON.stringify(payload);
    }
  };
};

const backgroundPath = path.join(__dirname, "..", "background.js");
vm.runInThisContext(fs.readFileSync(backgroundPath, "utf8"), { filename: backgroundPath });
assert.equal(typeof messageListener, "function");

function dispatch(message) {
  return new Promise((resolve) => {
    const keepAlive = messageListener(
      message,
      { id: chrome.runtime.id, url: shareUrl, tab: { url: shareUrl } },
      resolve
    );
    assert.equal(keepAlive, true);
  });
}

(async () => {
  const targets = await dispatch({ type: "mi:targets", shareUrl });
  assert.equal(targets.ok, true);
  assert.equal(targets.data.direct_link_contract_version, 2);
  assert.equal(targets.data.cloud_download_enabled, false);

  const transfer = await dispatch({
    type: "mi:transfer",
    shareUrl,
    targetPath: "",
    title: "花开锦绣",
    year: "2026",
    category: "tv",
    matchRename: false,
    destinationMode: "library",
    applyRenamePlan: true
  });
  assert.equal(transfer.ok, true);
  const transferRequest = requests.find((request) => request.url.endsWith("/api/transfers/direct-link"));
  assert.deepEqual(transferRequest.body, {
    link: shareUrl,
    save_path: "",
    title: "花开锦绣",
    year: "2026",
    category: "tv",
    match_rename: false,
    destination_mode: "library",
    apply_rename_plan: true
  });

  const preview = await dispatch({
    type: "mi:rename-preview",
    shareUrl,
    title: "花开锦绣",
    year: "2026",
    category: "tv"
  });
  assert.equal(preview.ok, true);
  assert.ok(requests.some((request) => request.url.endsWith("/api/transfers/direct-link/rename-preview")));

  backendContract = 1;
  const outdated = await dispatch({ type: "mi:targets", shareUrl });
  assert.equal(outdated.ok, false);
  assert.equal(outdated.error.code, "backend_contract_outdated");

  process.stdout.write("background contract tests passed\n");
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
