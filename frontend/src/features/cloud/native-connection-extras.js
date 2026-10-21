import { fieldsView, readFields, runAction, escapeHtml as esc } from "../../components/native-ui.js";

export function connectionExtrasView(config) {
  return `<details class="panel panel-pad"><summary>兼容服务与只读验证</summary>
    <section data-qas-compat><div class="panel-head"><div><h3>QAS 兼容连接</h3><small>保留已有 QAS 集成设置；夸克原生连接继续使用上方 Cookie</small></div></div>
      ${fieldsView([["qas_base_url", "QAS 地址"], ["qas_token", "QAS Token", "secret"]], config)}
      <div class="row-actions"><button class="mini-btn primary" data-qas-save>保存 QAS</button><button class="mini-btn" data-qas-test>测试已保存连接</button><button class="mini-btn" data-qas-search-status>读取 QAS 自带搜索状态</button></div><p class="inline-result" role="status"></p><div data-qas-search-control></div>
    </section>
    <section data-quark-inspect><div class="panel-head"><div><h3>夸克分享只读验证</h3><small>读取分享目录，不转存文件</small></div></div><div class="field"><label>分享链接</label><input class="input" data-inspect-link placeholder="https://pan.quark.cn/s/..."></div><button class="mini-btn" data-inspect-run>读取分享内容</button><p class="inline-result" role="status"></p><div data-inspect-files></div></section>
  </details>`;
}

export function bindConnectionExtras(api) {
  const qas = document.querySelector("[data-qas-compat]");
  if (qas) {
    const output = qas.querySelector('[role="status"]');
    qas.querySelector("[data-qas-save]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      await api("/api/config", { method: "PUT", body: JSON.stringify(readFields(qas)) });
      qas.querySelector('[data-field-type="secret"]').value = "";
      return { message: "QAS 设置已保存" };
    });
    qas.querySelector("[data-qas-test]").onclick = (event) => void runAction(event.currentTarget, output, () => api("/api/config/test-qas", { method: "POST" }));
    qas.querySelector("[data-qas-search-status]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      const result = await api("/api/config/qas-pansou");
      if (result.ok !== false) {
        const control = qas.querySelector("[data-qas-search-control]");
        control.innerHTML = `<label class="check"><input type="checkbox" ${result.enabled ? "checked" : ""}>QAS 自带搜索</label><button class="mini-btn">应用到 QAS</button>`;
        control.querySelector("button").onclick = (event) => void runAction(event.currentTarget, output, () => api("/api/config/qas-pansou", { method: "PUT", body: JSON.stringify({ enabled: control.querySelector("input").checked }) }));
      }
      return { ...result, message: result.message || `QAS 自带搜索${result.enabled ? "已开启" : "已关闭"}` };
    });
  }
  const inspect = document.querySelector("[data-quark-inspect]");
  if (inspect) inspect.querySelector("[data-inspect-run]").onclick = (event) => void runAction(event.currentTarget, inspect.querySelector('[role="status"]'), async () => {
    const result = await api("/api/config/quark/share/inspect", { method: "POST", body: JSON.stringify({ share_url: inspect.querySelector("[data-inspect-link]").value.trim() }) });
    inspect.querySelector("[data-inspect-files]").innerHTML = `<div class="list">${(result.files || []).map((file) => `<div class="list-row"><b>${esc(file.name)}</b><small>${file.is_dir ? "目录" : `${file.size || 0} B`}</small></div>`).join("")}</div>`;
    return result;
  });
}
