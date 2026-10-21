import { escapeHtml as esc, modal } from "../native-ui.js";

// Resolve every path segment using live provider IDs; never infer IDs from names.
export async function pickNativeDirectory(api, provider, onChoose, { startPath = "/", children = false, selected = [] } = {}) {
  const dialog = modal(children ? "选择一级子目录" : "选择网盘目录", `${provider === "p115" ? "115" : "夸克"} · 实时读取目录`);
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  let crumbs = [{ id: "0", name: "根目录" }];
  let entries = [];
  let busy = false;
  const chosen = new Set(selected);
  const path = () => "/" + crumbs.slice(1).map((c) => c.name).join("/");
  const list = async (id) => {
    const response = await api(`/api/cloud/${provider}/directory?parent_id=${encodeURIComponent(id)}`);
    return (Array.isArray(response) ? response : response.entries || []).filter((e) => e.is_dir);
  };
  function paint() {
    body.innerHTML = `<div class="picker-crumbs">${crumbs.map((c, i) => `<button class="mini-btn" data-dir-crumb="${i}" ${children || busy ? "disabled" : ""}>${esc(c.name)}</button>`).join('<span>/</span>')}</div>
      <p class="muted-note">${esc(path())}</p><div class="list">${entries.map((entry, i) => children
        ? `<label class="list-row"><input type="checkbox" data-dir-select="${i}" ${chosen.has(entry.name) ? "checked" : ""}><b>${esc(entry.name)}</b></label>`
        : `<button class="list-row native-directory-row" data-dir-open="${i}" ${busy ? "disabled" : ""}><span>▱</span><b>${esc(entry.name)}</b><span>›</span></button>`).join("") || '<p class="muted-note">当前目录没有子目录</p>'}</div>`;
    dialog.querySelector(".picker-foot").innerHTML = `<button class="mini-btn primary" data-dir-choose ${busy ? "disabled" : ""}>${children ? "使用所选子目录" : "使用当前目录"}</button>`;
    body.querySelectorAll("[data-dir-crumb]").forEach((button) => { button.onclick = () => { crumbs = crumbs.slice(0, Number(button.dataset.dirCrumb) + 1); void load(); }; });
    body.querySelectorAll("[data-dir-open]").forEach((button) => { button.onclick = () => { const e = entries[Number(button.dataset.dirOpen)]; crumbs.push({ id: e.file_id, name: e.name }); void load(); }; });
    body.querySelectorAll("[data-dir-select]").forEach((input) => { input.onchange = () => { const name = entries[Number(input.dataset.dirSelect)].name; input.checked ? chosen.add(name) : chosen.delete(name); }; });
    dialog.querySelector("[data-dir-choose]").onclick = () => {
      try { onChoose(children ? [...chosen] : path()); dialog.close(); }
      catch (error) { output.textContent = error.message; }
    };
  }
  async function load() {
    busy = true;
    entries = [];
    paint();
    output.textContent = "正在读取…";
    try {
      entries = await list(crumbs.at(-1).id);
      if (!dialog.isConnected) return;
      output.textContent = "";
      busy = false;
      paint();
    } catch (error) {
      if (!dialog.isConnected) return;
      // Failed listing cannot be accepted as an empty directory.
      output.textContent = error.message;
      busy = false;
      body.innerHTML = '<button class="mini-btn" data-dir-retry>重试读取</button>';
      body.querySelector("[data-dir-retry]").onclick = () => void load();
      dialog.querySelector(".picker-foot").replaceChildren();
    }
  }
  output.textContent = "正在定位目录…";
  try {
    for (const segment of startPath.replace(/\\/g, "/").split("/").filter(Boolean)) {
      const matches = (await list(crumbs.at(-1).id)).filter((e) => e.name === segment);
      if (matches.length !== 1) throw new Error(`无法唯一定位目录「${segment}」，请核对根路径`);
      crumbs.push({ id: matches[0].file_id, name: matches[0].name });
    }
    if (dialog.isConnected) await load();
  } catch (error) {
    output.textContent = error.message;
    body.innerHTML = '<button class="mini-btn" data-dir-root>从网盘根目录选择</button>';
    body.querySelector("[data-dir-root]").onclick = () => { crumbs = [{ id: "0", name: "根目录" }]; void load(); };
  }
}

export function attachDirectoryButton(api, inputId, provider, options = {}) {
  const input = document.getElementById(inputId);
  if (!input || input.parentElement.querySelector(`[data-directory-for="${inputId}"]`)) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "directory-icon";
  button.dataset.directoryFor = inputId;
  const label = options.children ? "选择一级子目录" : "选择目录";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-haspopup", "dialog");
  button.innerHTML = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>';
  const wrapper = document.createElement("div");
  wrapper.className = `directory-input${input.tagName === "TEXTAREA" ? " multiline" : ""}`;
  input.insertAdjacentElement("beforebegin", wrapper);
  wrapper.append(input, button);
  button.onclick = () => {
    const key = typeof provider === "function" ? provider() : provider;
    const startPath = typeof options.startPath === "function" ? options.startPath() : options.startPath || (options.mode === "local" ? "" : "/");
    if (options.children && !startPath.trim()) return;
    const picker = options.mode ? pickPathDirectory : pickNativeDirectory;
    void picker(api, key, (value) => {
      if (options.relativeRoot) {
        const root = options.relativeRoot.replace(/\/$/, "");
        if (root && value !== root && !value.startsWith(root + "/")) throw new Error("分类目录必须位于网盘根目录内");
        value = "/" + value.slice(root.length).replace(/^\//, "");
      }
      input.value = Array.isArray(value) ? value.join("\n") : value;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }, { ...options, startPath: options.mode ? input.value || startPath : startPath, selected: options.children ? input.value.split("\n").filter(Boolean) : [] });
  };
}

// Existing backend path browsers serve local mounts, QAS and the saved cross-copy route.
export async function pickPathDirectory(api, provider, onChoose, { mode, startPath = "" } = {}) {
  const dialog = modal("选择目录", mode === "local" ? "本机已挂载目录" : mode === "openlist" ? "已保存的跨盘连接" : "QAS 目录");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  const history = [];
  let current = startPath;
  async function load(path) {
    body.innerHTML = '<p class="muted-note">正在读取目录…</p>';
    dialog.querySelector(".picker-foot").replaceChildren();
    try {
      const endpoint = mode === "local" ? "/api/config/browse-local-path" : mode === "openlist" ? "/api/openlist/browse" : "/api/config/browse-provider-path";
      const result = await api(endpoint, { method: "POST", body: JSON.stringify(mode === "provider" ? { provider, path, complete: false, allow_missing: false } : { path }) });
      if (result.ok === false || result.exists === false) throw new Error(result.message || "目录不可访问");
      if (!dialog.isConnected) return;
      current = result.path || path;
      output.textContent = "";
      const directories = (result.directories || []).filter(entry => entry.is_dir);
      body.innerHTML = `<div class="picker-crumbs"><button class="mini-btn" data-path-back ${history.length ? "" : "disabled"}>返回上级</button><span>${esc(current)}</span></div><div class="list">${directories.map((entry,index) => `<button class="list-row native-directory-row" data-path-enter="${index}"><svg class="ic"><use href="#i-folder"/></svg><b>${esc(entry.name)}</b><span>›</span></button>`).join("") || '<p class="muted-note">当前目录没有子目录</p>'}</div>`;
      const rootButton = document.createElement("button");
      rootButton.className = "mini-btn";
      rootButton.textContent = "可选根目录";
      rootButton.onclick = () => { history.length = 0; void load(mode === "local" ? "" : "/"); };
      body.querySelector(".picker-crumbs").prepend(rootButton);
      body.querySelector("[data-path-back]").onclick = () => void load(history.pop());
      body.querySelectorAll("[data-path-enter]").forEach(button => { button.onclick = () => { history.push(current); void load(current.replace(/[\\/]$/, "") + "/" + directories[Number(button.dataset.pathEnter)].name); }; });
      dialog.querySelector(".picker-foot").innerHTML = '<button class="mini-btn primary" data-path-choose>使用当前目录</button>';
      dialog.querySelector("[data-path-choose]").onclick = () => { onChoose(current); dialog.close(); };
    } catch (error) {
      if (!dialog.isConnected) return;
      output.textContent = error.message;
      body.innerHTML = '<div class="row-actions"><button class="mini-btn" data-path-root>从可选根目录选择</button><button class="mini-btn" data-path-retry>重试读取</button></div>';
      body.querySelector("[data-path-root]").onclick = () => { history.length = 0; void load(mode === "local" ? "" : "/"); };
      body.querySelector("[data-path-retry]").onclick = () => void load(path);
    }
  }
  await load(current);
}
