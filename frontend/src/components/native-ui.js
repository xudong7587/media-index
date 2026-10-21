// DOM components shared by the framework-free frontend.
export const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const listeners = new WeakMap();
export function listen(node, event, handler) {
  if (!node) return;
  const registered = listeners.get(node) || new Map();
  if (registered.has(event)) node.removeEventListener(event, registered.get(event));
  registered.set(event, handler);
  listeners.set(node, registered);
  node.addEventListener(event, handler);
}

export function modal(title, subtitle = "", className = "") {
  const dialog = document.createElement("dialog");
  dialog.className = `picker-dialog native-dialog ${className}`;
  dialog.innerHTML = `<div class="picker-head"><div><h2>${escapeHtml(title)}</h2><small>${escapeHtml(subtitle)}</small></div><button class="icon-btn" data-dismiss aria-label="关闭">×</button></div><div class="native-dialog-body"></div><p class="inline-result native-result" role="status"></p><div class="picker-foot"></div>`;
  dialog.querySelector("[data-dismiss]").onclick = () => dialog.close();
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

export async function runAction(button, output, work) {
  if (button?.disabled) return;
  if (button) button.disabled = true;
  if (output) { output.classList.remove("error"); output.textContent = "正在处理…"; }
  try {
    const result = await work();
    if (result?.ok === false) throw new Error(result.message || "操作未完成");
    if (output) output.textContent = result?.message || "操作完成";
    return result;
  } catch (error) {
    if (output) { output.classList.add("error"); output.textContent = error.message; }
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

export function fieldsView(fields, config) {
  return `<div class="form-grid native-form">${fields.map(([key, label, type = "text", choices]) => {
    const id = `extra-${key}`;
    const value = config[key];
    if (type === "boolean") return `<div class="switch-row"><div><b>${escapeHtml(label)}</b></div><button class="switch" role="switch" id="${id}" data-config-field="${key}" data-field-type="${type}" aria-label="${escapeHtml(label)}" aria-checked="${Boolean(value)}"></button></div>`;
    let input;
    if (Array.isArray(choices)) input = `<select class="input" id="${id}" data-config-field="${key}" data-field-type="${type}">${choices.map(([v, text]) => `<option value="${escapeHtml(v)}" ${String(v) === String(value) ? "selected" : ""}>${escapeHtml(text)}</option>`).join("")}</select>`;
    else if (type === "json" || type === "lines") input = `<textarea class="input" rows="4" id="${id}" data-config-field="${key}" data-field-type="${type}">${escapeHtml(type === "json" ? JSON.stringify(value || {}, null, 2) : (value || []).join("\n"))}</textarea>`;
    else input = `<input class="input" id="${id}" data-config-field="${key}" data-field-type="${type}" type="${type === "secret" ? "password" : type}" value="${type === "secret" ? "" : escapeHtml(value ?? "")}" ${type === "secret" ? 'placeholder="留空保留已保存的密钥" autocomplete="new-password"' : ""} />`;
    return `<div class="field"><label for="${id}">${escapeHtml(label)}</label>${input}</div>`;
  }).join("")}</div>`;
}

export function readFields(container) {
  const payload = {};
  container.querySelectorAll("[data-config-field]").forEach((node) => {
    const key = node.dataset.configField;
    const type = node.dataset.fieldType;
    if (type === "secret" && !node.value.trim()) return;
    if (type === "boolean") payload[key] = node.getAttribute("aria-checked") === "true";
    else if (type === "number") {
      if (!node.value.trim() || !Number.isFinite(Number(node.value))) throw new Error("请填写有效数字");
      payload[key] = Number(node.value);
    } else if (type === "lines") payload[key] = node.value.split("\n").map((v) => v.trim()).filter(Boolean);
    else if (type === "json") payload[key] = JSON.parse(node.value);
    else payload[key] = node.value.trim();
  });
  return payload;
}

export function bindFields(container) {
  container.querySelectorAll('[data-field-type="boolean"]').forEach((node) => listen(node, "click", () => node.setAttribute("aria-checked", String(node.getAttribute("aria-checked") !== "true"))));
}
