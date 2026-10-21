import { escapeHtml as esc, runAction } from "../../components/native-ui.js";

export function diagnosticSupportView() {
  return `<section class="panel panel-pad" data-diagnostic-support>
    <div class="panel-head"><div><h2>临时支持令牌</h2><small>只读诊断权限，5–120 分钟有效，关闭远程诊断会撤销令牌</small></div></div>
    <p data-support-status>正在读取授权状态…</p>
    <div class="field"><label for="diagnosticTtl">有效期（分钟）</label><input class="input" id="diagnosticTtl" type="number" min="5" max="120" value="30"></div>
    <div class="row-actions"><button class="mini-btn primary" data-support-create disabled>创建临时令牌</button><button class="mini-btn" data-support-revoke disabled>撤销全部令牌</button></div>
    <div data-support-token></div><p class="inline-result" role="status"></p>
    <p class="muted-note">令牌仅在创建时显示，请通过 HTTPS 使用。权限不包含原始日志、凭据、命令执行或写入操作。</p>
  </section>`;
}

export async function bindDiagnosticSupport(api) {
  const panel = document.querySelector("[data-diagnostic-support]");
  if (!panel) return;
  const output = panel.querySelector('[role="status"]');
  const create = panel.querySelector("[data-support-create]");
  const revoke = panel.querySelector("[data-support-revoke]");
  async function refresh() {
    const status = await api("/api/diagnostics/support/status");
    if (!panel.isConnected) return;
    panel.querySelector("[data-support-status]").textContent = `${status.enabled ? "远程诊断已开启" : "远程诊断已关闭"} · 有效令牌 ${status.active_token_count} 个${status.next_expiry ? ` · 最近到期 ${status.next_expiry}` : ""}`;
    create.disabled = !status.enabled;
    revoke.disabled = !status.active_token_count;
  }
  create.onclick = async () => {
    await runAction(create, output, async () => {
      const ttl = Number(panel.querySelector("#diagnosticTtl").value);
      if (!Number.isInteger(ttl) || ttl < 5 || ttl > 120) throw new Error("有效期须为 5–120 分钟");
      const result = await api("/api/diagnostics/support/tokens", { method: "POST", body: JSON.stringify({ ttl_minutes: ttl }) });
      if (panel.isConnected) {
        panel.querySelector("[data-support-token]").innerHTML = `<div class="field"><label>临时令牌（本页关闭后不再显示）</label><input class="input" readonly type="password" value="${esc(result.token)}"><small>到期：${esc(result.expires_at)}</small><button class="mini-btn" data-copy-token>复制令牌</button></div>`;
        panel.querySelector("[data-copy-token]").onclick = (event) => void runAction(event.currentTarget, output, async () => { await navigator.clipboard.writeText(result.token); return { message: "令牌已复制" }; });
      }
      return { message: "令牌已创建" };
    });
    await refresh().catch((e) => { output.textContent = e.message; });
  };
  revoke.onclick = async () => {
    await runAction(revoke, output, async () => {
      const result = await api("/api/diagnostics/support/tokens", { method: "DELETE" });
      panel.querySelector("[data-support-token]").replaceChildren();
      return { message: `已撤销 ${result.revoked} 个令牌` };
    });
    await refresh().catch((e) => { output.textContent = e.message; });
  };
  await refresh().catch((e) => { output.textContent = e.message; });
}
