function crossManualView() {
  const selected = crossState.selected;
  const rows = (entries, side) => entries.map((entry) => `<label class="copy-row"><input type="checkbox" data-copy-pick="${esc(entry.name)}" data-side="${side}" ${selected.has(entry.name) && side === "source" ? "checked" : ""} /><svg class="ic"><use href="#${entry.is_dir ? "i-folder" : "i-doc"}"/></svg><span ${entry.is_dir ? `data-copy-enter="${esc(entry.name)}"` : ""}>${esc(entry.name)}</span><time>${esc((entry.updated_at || entry.modified || "").slice(5, 10))}</time></label>`).join("");
  return `
  <section class="panel">
    <div class="panel-head">
      <div><h2>手动复制</h2><small>勾选左侧条目，选择目标目录后复制</small></div>
      <div class="chip-row"><button class="chip mini${crossState.overwrite ? "" : " active"}" data-copy-mode="skip">跳过已存在</button><button class="chip mini${crossState.overwrite ? " active" : ""}" data-copy-mode="overwrite">覆盖已存在</button></div>
    </div>
    <div class="copy-grid">
      <div class="copy-pane">
        <div class="copy-head"><b>夸克媒体库</b><small>${esc(crossState.source || "/")}</small><div class="row-actions"><button class="mini-btn" data-copy-up="source">上一级</button><button class="mini-btn" data-copy-refresh="source">刷新</button></div></div>
        ${crossState.sourceEntries.length ? rows(crossState.sourceEntries, "source") : `<div class="empty-state"><b>目录为空或未读取</b><span>点刷新读取当前目录</span></div>`}
      </div>
      <div class="copy-mid">
        <button class="copy-go" data-copy-run ${selected.size ? "" : "disabled"} title="复制到 115">→</button>
        <span class="copy-count">已选 ${selected.size}</span>
      </div>
      <div class="copy-pane">
        <div class="copy-head"><b>115 媒体库</b><small>${esc(crossState.target || "/")}</small><div class="row-actions"><button class="mini-btn" data-copy-up="target">上一级</button><button class="mini-btn" data-copy-refresh="target">刷新</button></div></div>
        ${crossState.targetEntries.length ? rows(crossState.targetEntries, "target") : `<div class="empty-state"><b>目标目录为空或未读取</b><span>点刷新读取当前目录</span></div>`}
      </div>
    </div>
    ${crossState.message ? `<p class="inline-result ${crossState.ok ? "ok" : "error"}" style="padding:0 18px 14px">${esc(crossState.message)}</p>` : ""}
  </section>`;
}

async function loadCopyPane(side) {
  const path = side === "source" ? crossState.source : crossState.target;
  try {
    const result = await api("/api/openlist/entries", { method: "POST", body: JSON.stringify({ path }) });
    const entries = (result.entries || []).map((entry) => ({ ...entry, updated_at: entry.updated_at || entry.modified_at || "" }));
    if (side === "source") crossState.sourceEntries = entries; else crossState.targetEntries = entries;
    crossState.ok = true;
    crossState.message = "";
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  await loadCross();
}

function bindCopy() {
  document.querySelectorAll("[data-copy-refresh]").forEach((button) => button.addEventListener("click", () => void loadCopyPane(button.dataset.copyRefresh)));
  document.querySelectorAll("[data-copy-up]").forEach((button) => button.addEventListener("click", () => {
    const side = button.dataset.copyUp;
    const path = side === "source" ? crossState.source : crossState.target;
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    if (side === "source") crossState.source = parent; else crossState.target = parent;
    void loadCopyPane(side);
  }));
  document.querySelectorAll("[data-copy-enter]").forEach((node) => node.addEventListener("click", () => {
    const side = node.closest(".copy-pane")?.querySelector("[data-copy-refresh]")?.dataset.copyRefresh || "source";
    const base = (side === "source" ? crossState.source : crossState.target).replace(/\/$/, "");
    const next = `${base}/${node.dataset.copyEnter}`;
    if (side === "source") crossState.source = next; else crossState.target = next;
    void loadCopyPane(side);
  }));
  document.querySelectorAll("[data-copy-pick]").forEach((input) => input.addEventListener("change", () => {
    if (input.dataset.side !== "source") return;
    if (input.checked) crossState.selected.add(input.dataset.copyPick); else crossState.selected.delete(input.dataset.copyPick);
    const button = document.querySelector("[data-copy-run]");
    if (button) button.disabled = crossState.selected.size === 0;
    const count = document.querySelector(".copy-count");
    if (count) count.textContent = `已选 ${crossState.selected.size}`;
  }));
  document.querySelectorAll("[data-copy-mode]").forEach((button) => button.addEventListener("click", () => {
    crossState.overwrite = button.dataset.copyMode === "overwrite";
    void loadCross();
  }));
  document.querySelector("[data-copy-run]")?.addEventListener("click", () => void runCopy());
}

async function runCopy() {
  if (!crossState.selected.size) return;
  crossState.busy = true;
  try {
    const result = await api("/api/openlist/sync-selected", { method: "POST", body: JSON.stringify({ source_dir: crossState.source, target_dir: crossState.target, names: [...crossState.selected], overwrite: Boolean(crossState.overwrite) }) });
    crossState.ok = true; crossState.message = result.message || "复制任务已提交"; crossState.selected = new Set();
  } catch (error) { crossState.ok = false; crossState.message = error.message; }
  crossState.busy = false;
  await loadCross();
}

