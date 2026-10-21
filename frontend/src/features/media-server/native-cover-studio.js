import { escapeHtml as esc, modal, fieldsView, readFields, bindFields, runAction } from "../../components/native-ui.js";

const defaults = {
  resolution: "1080p", source_sort: "Random", image_source: "Primary", zh_title: "", en_title: "",
  zh_font_id: "default", en_font_id: "default", zh_font_size: 170, en_font_size: 75, title_scale: 1,
  title_x_offset: 0, zh_font_offset: 0, title_spacing: 40, en_line_spacing: 40,
  blur_size: 50, showcase_blur: true, color_ratio: 0.8, bg_color_mode: "auto", custom_bg_color: "#2f6f57",
};
const choices = (...values) => values.map((v) => Array.isArray(v) ? v : [v, v]);
const optionGroups = [
  ["画面", [
    ["resolution", "输出规格", "text", choices("1080p", "720p", "480p")],
    ["image_source", "图片来源", "text", choices(["Primary", "海报"], ["Backdrop", "背景图"])],
    ["source_sort", "取样排序", "text", choices(["Random", "随机"], ["DateCreated", "入库时间"], ["PremiereDate", "首播时间"])],
    ["showcase_blur", "模糊背景", "boolean"],
    ["bg_color_mode", "背景颜色", "text", choices(["auto", "自动提取"], ["custom", "自定义"])],
    ["custom_bg_color", "自定义颜色", "color"],
  ]],
  ["标题", [
    ["zh_title", "中文标题（按媒体库保存）"], ["en_title", "英文标题（按媒体库保存）"],
    ["zh_font_size", "中文字号", "number"], ["en_font_size", "英文字号", "number"],
    ["title_scale", "标题缩放", "number"], ["title_x_offset", "水平偏移", "number"],
    ["zh_font_offset", "中文垂直偏移", "number"], ["title_spacing", "中英文间距", "number"],
    ["en_line_spacing", "英文行间距", "number"],
  ]],
  ["细节", [
    ["blur_size", "背景模糊", "number"], ["color_ratio", "背景颜色比例（0–1）", "number"],
  ]],
];

export async function openNativeCoverStudio(api, libraries, onSaved) {
  const dialog = modal("媒体库封面工坊", "调整画面、字体与标题，预览后写入 Emby", "native-cover-studio");
  const body = dialog.querySelector(".native-dialog-body");
  const output = dialog.querySelector('[role="status"]');
  try {
    const [config, fontResult] = await Promise.all([api("/api/config/status"), api("/api/integrations/emby/libraries/covers/fonts")]);
    if (!dialog.isConnected) return;
    let fonts = fontResult.fonts || [];
    let baseOptions = { ...defaults, ...config.emby_cover_options };
    const perLibrary = structuredClone(config.emby_cover_library_options || {});
    let libraryId = String(libraries[0]?.id || "");
    let sample = 0;
    let timer;
    const currentLibrary = () => libraries.find((lib) => String(lib.id) === libraryId);
    const options = () => ({ ...baseOptions, zh_title: perLibrary[libraryId]?.zh_title || "", en_title: perLibrary[libraryId]?.en_title || "" });
    body.innerHTML = `<div class="panel-head"><div><p class="eyebrow">MEDIA COVER ATELIER</p><h3>封面控制台</h3></div><button class="mini-btn" data-cover-sample>重新取样</button></div>
      <div class="form-grid native-form"><div class="field"><label>预览媒体库</label><select class="input" data-studio-library>${libraries.map((lib) => `<option value="${esc(lib.id)}">${esc(lib.name)}</option>`).join("")}</select></div><div class="field"><label>风格</label><select class="input" data-studio-style>${choices(["collage", "拼贴"], ["showcase", "陈列"], ["mosaic", "马赛克"], ["minimal", "极简"]).map(([v, text]) => `<option value="${v}" ${v === config.emby_cover_style ? "selected" : ""}>${text}</option>`).join("")}</select></div></div>
      <div class="native-studio-grid"><aside><div class="native-cover-preview"><img alt="封面实时预览"><span data-preview-status>准备预览</span></div><p class="muted-note">预览不会替换现有封面。</p></aside>
        <div data-cover-options></div></div>
      <section class="panel panel-pad"><div class="panel-head"><div><h3>刷新计划</h3><small>未勾选媒体库时，批量刷新与定时任务处理全部媒体库</small></div></div>
        ${fieldsView([["emby_cover_refresh_enabled", "定时更新封面", "boolean"], ["emby_cover_refresh_cron", "Cron 计划"], ["emby_cover_refresh_hours", "备用间隔（小时）", "number"]], config)}
        <div class="chip-row">${libraries.map((lib) => `<label class="check"><input type="checkbox" data-studio-include="${esc(lib.id)}" ${(config.emby_cover_library_ids || []).includes(lib.id) ? "checked" : ""}>${esc(lib.name)}</label>`).join("")}</div>
      </section>`;
    const controls = body.querySelector("[data-cover-options]");
    const image = body.querySelector(".native-cover-preview img");
    const previewStatus = body.querySelector("[data-preview-status]");
    const style = () => body.querySelector("[data-studio-style]").value;
    bindFields(body);
    function capture() {
      const next = readFields(controls);
      perLibrary[libraryId] = { ...(perLibrary[libraryId] || {}), zh_title: next.zh_title || "", en_title: next.en_title || "" };
      baseOptions = { ...baseOptions, ...next, zh_title: "", en_title: "" };
    }
    function preview() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!dialog.isConnected || !currentLibrary()) { previewStatus.textContent = "没有可预览的媒体库"; return; }
        try { capture(); } catch (error) { previewStatus.textContent = error.message; return; }
        previewStatus.textContent = "正在生成预览…";
        image.onload = () => { previewStatus.textContent = ""; };
        image.onerror = () => { previewStatus.textContent = "预览失败，请检查 Emby、海报和字体配置"; };
        const query = new URLSearchParams({ title: currentLibrary().name, style: style(), options: JSON.stringify(options()), sample: String(sample) });
        image.src = `/api/integrations/emby/libraries/${encodeURIComponent(libraryId)}/cover-preview?${query}`;
      }, 300);
    }
    function paintControls() {
      const current = options();
      controls.innerHTML = optionGroups.map(([name, fields], index) => `<details class="native-options" ${index === 0 ? "open" : ""}><summary>${name}</summary>${fieldsView(fields, current)}</details>`).join("") + `<details class="native-options"><summary>字体</summary>${fieldsView([
        ["zh_font_id", "中文字体", "text", fonts.map((f) => [f.id, f.label])],
        ["en_font_id", "英文字体", "text", fonts.map((f) => [f.id, f.label])],
      ], current)}<label class="mini-btn">上传字体<input type="file" data-studio-font accept=".ttf,.otf,.ttc" hidden></label><p class="muted-note">支持 TTF / OTF / TTC，最大 12 MB。上传后从字体列表选择。</p></details>`;
      controls.querySelectorAll('input[type="number"]').forEach((input) => { input.step = "any"; });
      bindFields(controls);
      controls.querySelectorAll("input,select,textarea").forEach((input) => input.addEventListener("change", preview));
      controls.querySelectorAll(".switch").forEach((button) => button.addEventListener("click", preview));
      controls.querySelector("[data-studio-font]").onchange = async (event) => {
        const file = event.target.files?.[0];
        if (!file) return;
        await runAction(null, output, async () => {
          if (file.size > 12 * 1024 * 1024) throw new Error("字体文件不能超过 12 MB");
          capture();
          const result = await api(`/api/integrations/emby/libraries/covers/fonts?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
          fonts = [...fonts.filter((font) => font.id !== result.font.id), result.font];
          paintControls();
          return result;
        });
      };
    }
    paintControls();
    body.querySelector("[data-studio-library]").onchange = (event) => { capture(); libraryId = event.target.value; paintControls(); preview(); };
    body.querySelector("[data-studio-style]").onchange = preview;
    body.querySelector("[data-cover-sample]").onclick = () => { sample += 1; preview(); };
    dialog.querySelector(".picker-foot").innerHTML = `<button class="mini-btn" data-studio-save>保存配置</button><button class="mini-btn" data-studio-apply ${libraryId ? "" : "disabled"}>替换当前媒体库封面</button><button class="mini-btn primary" data-studio-all ${libraries.length ? "" : "disabled"}>批量替换封面</button>`;
    const included = () => [...body.querySelectorAll("[data-studio-include]:checked")].map((node) => node.dataset.studioInclude);
    const libraryOptions = () => Object.fromEntries(Object.entries(perLibrary).map(([key, value]) => [key, { ...baseOptions, zh_title: value.zh_title || "", en_title: value.en_title || "" }]));
    dialog.querySelector("[data-studio-save]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      capture();
      const schedule = readFields(body.querySelector("section.panel"));
      await api("/api/config", { method: "PUT", body: JSON.stringify({ ...schedule, emby_cover_style: style(), emby_cover_options: baseOptions, emby_cover_library_ids: included(), emby_cover_library_options: libraryOptions() }) });
      await onSaved();
      return { message: "封面参数与计划已保存" };
    });
    dialog.querySelector("[data-studio-apply]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      capture();
      const result = await api(`/api/integrations/emby/libraries/${encodeURIComponent(libraryId)}/cover`, { method: "POST", body: JSON.stringify({ title: currentLibrary().name, style: style(), options: options() }) });
      await onSaved();
      return result;
    });
    dialog.querySelector("[data-studio-all]").onclick = (event) => void runAction(event.currentTarget, output, async () => {
      capture();
      const result = await api("/api/integrations/emby/libraries/covers/refresh", { method: "POST", body: JSON.stringify({ style: style(), options: baseOptions, library_ids: included(), library_options: libraryOptions() }) });
      await onSaved();
      return result;
    });
    dialog.addEventListener("close", () => clearTimeout(timer));
    preview();
  } catch (error) { output.textContent = error.message; }
}
