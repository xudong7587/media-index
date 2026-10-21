import { escapeHtml as esc, runAction } from "../../components/native-ui.js";

export async function renderStrmStatus(api, panel) {
  if (!panel) return;
  try {
    const [entriesResult, deletionsResult] = await Promise.allSettled([api("/api/cloud/strm?limit=100"), api("/api/cloud/deletion-intents?limit=50")]);
    if (!panel.isConnected) return;
    const entries = entriesResult.status === "fulfilled" ? entriesResult.value : [];
    const intents = deletionsResult.status === "fulfilled" ? deletionsResult.value : [];
    panel.innerHTML = `<div class="panel-head"><div><h2>STRM 记录与删除联动</h2><small>读取最近生成记录；删除联动须由后端核验精确资产映射</small></div><button class="mini-btn" data-strm-status-refresh>刷新</button></div>
      ${entriesResult.status === "rejected" ? `<p class="inline-result error">${esc(entriesResult.reason.message)}</p>` : `<details class="native-options"><summary>最近 STRM 记录 · ${entries.length}</summary><div class="list">${entries.map((entry) => `<div class="list-row"><div class="grow"><b>${esc(entry.asset_name)}</b><small>${esc(entry.relative_path)}${entry.last_error_safe ? ` · ${esc(entry.last_error_safe)}` : ""}</small></div><span class="pill">${esc(entry.status)}</span></div>`).join("") || '<p class="muted-note">还没有生成记录</p>'}</div></details>`}
      <h3>删除事件</h3>${deletionsResult.status === "rejected" ? `<p class="inline-result error">${esc(deletionsResult.reason.message)}</p>` : `<div class="list">${intents.map((intent) => `<div class="list-row"><div class="grow"><b>${esc(intent.asset_name)}</b><small>${esc(intent.message_safe || intent.requested_at)}</small></div><span class="pill">${esc(intent.state)}</span>${intent.state === "requested" ? `<button class="mini-btn danger" data-deletion-confirm="${intent.id}">核验并移入回收站</button>` : ""}</div>`).join("") || '<p class="muted-note">暂无删除事件</p>'}</div>`}<p class="inline-result" role="status"></p>`;
    panel.querySelector("[data-strm-status-refresh]").onclick = () => void renderStrmStatus(api, panel);
    panel.querySelectorAll("[data-deletion-confirm]").forEach((button) => { button.onclick = () => {
      if (!confirm("确认让后端核验此删除事件，并将精确匹配的网盘源文件移入回收站？")) return;
      void runAction(button, panel.querySelector('[role="status"]'), async () => {
        const result = await api(`/api/cloud/deletion-intents/${button.dataset.deletionConfirm}/confirm`, { method: "POST" });
        await renderStrmStatus(api, panel);
        return result;
      });
    }; });
  } catch (error) { panel.textContent = error.message; }
}
