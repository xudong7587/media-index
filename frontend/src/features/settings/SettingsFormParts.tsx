import { SettingsToggle, SettingsInput, InlineHelp, savedInputPlaceholder } from "../../components/settings/SettingsFields";
export { SettingsToggle, SettingsInput, InlineHelp, savedInputPlaceholder };
import React, { useState } from "react";
import { CheckCircle, DotsSixVertical, Eye, EyeSlash, FolderOpen, MinusCircle, PlusCircle, Question, WarningCircle } from "@phosphor-icons/react";
import { api, ConfigStatus } from "../../lib/api";

export function buildConfigPayload(form: Record<string, string>) {
  const payload: Record<string, string | number | boolean | string[] | Record<string, string>> = {};
  const categoryPaths: Record<string, string> = {};
  const qasCategoryPaths: Record<string, string> = {};
  const p115CategoryPaths: Record<string, string> = {};
  const quarkCategoryPaths: Record<string, string> = {};
  Object.entries(form).forEach(([key, value]) => {
    if (key.startsWith("category_paths.")) {
      categoryPaths[key.replace("category_paths.", "")] = value.trim();
      return;
    }
    if (key.startsWith("qas_category_paths.")) {
      qasCategoryPaths[key.replace("qas_category_paths.", "")] = value.trim();
      return;
    }
    if (key.startsWith("p115_category_paths.")) {
      p115CategoryPaths[key.replace("p115_category_paths.", "")] = value.trim();
      return;
    }
    if (key.startsWith("quark_category_paths.")) {
      quarkCategoryPaths[key.replace("quark_category_paths.", "")] = value.trim();
      return;
    }
    if (!value.trim() && key !== "proxy_url" && key !== "quality_priority_keywords" && key !== "resource_excluded_keywords") return;
    if (["tmdb_adult_content_enabled", "wishlist_scheduler_enabled", "tracking_scheduler_enabled", "notification_external_enabled", "telegram_enabled", "wecom_enabled", "season_subdirectory_enabled", "openlist_enabled", "openlist_auto_sync"].includes(key)) {
      payload[key] = value === "true";
      return;
    }
    if (["wishlist_poll_minutes", "wishlist_default_check_hour", "tracking_poll_minutes", "tracking_retry_interval_minutes", "tracking_max_retries"].includes(key)) {
      payload[key] = Number(value);
      return;
    }
    if (key === "enabled_providers") {
      payload[key] = value.split(",").map((item) => item.trim()).filter(Boolean);
      return;
    }
    if (key === "quality_priority_keywords") {
      payload[key] = value.split("\n").map((item) => item.trim()).filter(Boolean);
      return;
    }
    if (key === "resource_excluded_keywords") {
      payload[key] = value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
      return;
    }
    payload[key] = value.trim();
  });
  if (Object.keys(categoryPaths).length) payload.category_paths = categoryPaths;
  if (Object.keys(qasCategoryPaths).length) payload.qas_category_paths = qasCategoryPaths;
  if (Object.keys(p115CategoryPaths).length) payload.p115_category_paths = p115CategoryPaths;
  if (Object.keys(quarkCategoryPaths).length) payload.quark_category_paths = quarkCategoryPaths;
  return payload;
}

export function SettingsNumberInput({ label, name, value, placeholder, min, max, onChange }: {
  label: string;
  name: string;
  value: string;
  placeholder: string;
  min: number;
  max: number;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input type="number" inputMode="numeric" value={value} placeholder={`${placeholder}，范围 ${min}-${max}`} min={min} max={max} onChange={(event) => onChange(name, event.target.value)} />
    </label>
  );
}

export function ProviderConnectionStatus({ connected, label }: { connected: boolean; label: string }) {
  const text = connected ? `${label} 已连接` : `${label} 未连接`;
  return (
    <span className={`provider-connection-status ${connected ? "connected" : "disconnected"}`} title={text} aria-label={text}>
      {connected ? <CheckCircle size={20} weight="fill" /> : <WarningCircle size={20} weight="fill" />}
    </span>
  );
}

export function QualityPrioritySettings({ config, form, onChange }: {
  config: ConfigStatus;
  form: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  const configured = form.quality_priority_keywords
    ? form.quality_priority_keywords.split("\n").map((item) => item.trim()).filter(Boolean)
    : config.quality_priority_keywords;
  const [dragging, setDragging] = useState<number | null>(null);
  const [customKeyword, setCustomKeyword] = useState("");
  const [customError, setCustomError] = useState("");

  function update(next: string[]) {
    onChange("quality_priority_keywords", next.join("\n"));
  }

  function remove(index: number) {
    if (configured.length <= 1) return;
    update(configured.filter((_item, itemIndex) => itemIndex !== index));
  }

  function addCustomKeyword() {
    const value = customKeyword.trim();
    if (!value) {
      setCustomError("请输入质量关键词");
      return;
    }
    const identity = value.normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase();
    if (configured.some((item) => item.normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase() === identity)) {
      setCustomError("这个质量关键词已经存在");
      return;
    }
    update([...configured, value]);
    setCustomKeyword("");
    setCustomError("");
  }

  return (
    <div className="quality-priority-settings">
      <p className="quality-priority-instruction">从左到右优先级递减，可拖动调整顺序。</p>
      <div className="quality-priority-list" aria-label="转存质量优先级">
        {configured.map((keyword, index) => (
          <div
            className={`quality-priority-item ${dragging === index ? "dragging" : ""}`}
            draggable
            key={`${keyword}-${index}`}
            onDragStart={() => setDragging(index)}
            onDragEnd={() => setDragging(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (dragging === null || dragging === index) return;
              const next = [...configured];
              const [item] = next.splice(dragging, 1);
              next.splice(index, 0, item);
              update(next);
              setDragging(null);
            }}
          >
            <DotsSixVertical className="quality-priority-grip" aria-hidden />
            <span className="quality-priority-name">{keyword}</span>
            <button type="button" className="quality-priority-remove" onClick={() => remove(index)} disabled={configured.length <= 1} title={`删除 ${keyword}`} aria-label={`删除 ${keyword}`}><MinusCircle size={16} weight="fill" /></button>
          </div>
        ))}
      </div>
      <div className="quality-priority-custom-editor">
        <label>
          <span>新增自定义质量</span>
          <input
            value={customKeyword}
            placeholder="例如：1080P REMUX"
            aria-label="自定义质量关键词"
            onChange={(event) => { setCustomKeyword(event.target.value); setCustomError(""); }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addCustomKeyword();
              }
            }}
          />
        </label>
        <button type="button" className="quality-priority-add" onClick={addCustomKeyword}>
          <PlusCircle size={19} weight="bold" />
          <span>添加</span>
        </button>
        {customError && <small role="alert">{customError}</small>}
      </div>
      <p className="settings-help">默认包含：4K 原盘、4K DV、4K HDR、4K SDR、4K、1080P HDR、1080P、720P、WEB-DL、WEBRip、SDR。匹配会兼容 2160P、Remux、杜比视界等常见写法。</p>
    </div>
  );
}

export function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="filter-row">
      <span>{label}</span>
      {children}
    </div>
  );
}

const defaultCategoryRows = [
  ["movie", "电影"],
  ["tv", "电视剧"],
  ["variety", "综艺"],
  ["concert", "演唱会"],
  ["documentary", "纪录片"],
  ["anime", "动漫"],
] as const;

const defaultCategoryPaths: Record<string, string> = {
  movie: "/01电影",
  tv: "/03电视剧",
  variety: "/04综艺",
  concert: "/05演唱会",
  documentary: "/06纪录片",
  anime: "/12动漫",
};

export function CategoryPathSettings({ config, form, onChange, provider = "qas", canPickPath = false, onPickPath }: {
  config: ConfigStatus;
  form: Record<string, string>;
  onChange: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  provider?: "common" | "qas" | "quark" | "p115";
  canPickPath?: boolean;
  onPickPath?: (key: string, label: string) => void;
}) {
  const prefix = provider === "common" ? "category_paths" : `${provider}_category_paths`;
  const configured = provider === "common" ? config.category_paths : provider === "p115" ? config.p115_category_paths : provider === "quark" ? config.quark_category_paths : config.qas_category_paths;
  const [visibleKeys, setVisibleKeys] = useState<string[]>(() => {
    const configuredKeys = Object.keys(configured || {});
    return [
      ...defaultCategoryRows.map(([key]) => key).filter((key) => configuredKeys.includes(key)),
      ...configuredKeys.filter((key) => !defaultCategoryRows.some(([known]) => known === key)),
    ];
  });
  const [customKey, setCustomKey] = useState("");
  const [customError, setCustomError] = useState("");

  function updatePath(key: string, value: string) {
    onChange((current) => ({ ...current, [`${prefix}.${key}`]: value }));
  }

  function currentPath(key: string) {
    return form[`${prefix}.${key}`] ?? configured?.[key] ?? defaultCategoryPaths[key] ?? `/${key}`;
  }

  function removePath(key: string) {
    if (visibleKeys.length <= 1) return;
    const remaining = visibleKeys.filter((item) => item !== key);
    onChange((current) => {
      const next = { ...current, [`${prefix}.${key}`]: "" };
      remaining.forEach((item) => {
        next[`${prefix}.${item}`] = current[`${prefix}.${item}`] ?? configured?.[item] ?? defaultCategoryPaths[item] ?? `/${item}`;
      });
      return next;
    });
    setVisibleKeys(remaining);
  }

  function addCustomPath() {
    const key = customKey.trim();
    if (!key) {
      setCustomError("请输入分类标识");
      return;
    }
    if (!/^[^\s./\\]+$/u.test(key)) {
      setCustomError("分类标识不能包含空格、点或斜杠");
      return;
    }
    if (visibleKeys.some((item) => item.toLocaleLowerCase() === key.toLocaleLowerCase())) {
      setCustomError("这个分类已经存在");
      return;
    }
    setVisibleKeys((current) => [...current, key]);
    updatePath(key, `/${key}`);
    setCustomKey("");
    setCustomError("");
  }

  const cloudRoot = (provider === "common" ? form.cloud_save_path || config.cloud_root : provider === "p115" ? form.p115_root_path || config.p115_root_path : provider === "quark" ? form.quark_root_path || config.quark_root_path : form.qas_save_path || config.qas_root || config.cloud_root).replace(/\/$/, "");
  const localRoot = (form.local_save_path || config.local_root || "/下载_未整理").replace(/\/$/, "");
  const tvCategory = (form[`${prefix}.variety`] || configured?.variety || "/tv").replace(/^\/?/, "/");

  return (
    <>
      <p className="muted">综艺路径示例：网盘 <code>{cloudRoot}{tvCategory}</code>；本地 <code>{localRoot}{tvCategory}</code>。媒体名称会继续追加在后面。</p>
      <div className="category-path-grid">
        {visibleKeys.map((key) => {
          const label = defaultCategoryRows.find(([known]) => known === key)?.[1] || key;
          const current = currentPath(key);
          return (
            <div className="category-path-field" key={key}>
              <label>
                <span>{label}</span>
                <input value={current} placeholder={current} onChange={(event) => updatePath(key, event.target.value)} />
              </label>
              {canPickPath && onPickPath && <button type="button" className="category-row-action pick" onClick={() => onPickPath(key, label)} title={`选择${label}路径`} aria-label={`选择${label}路径`}>
                <FolderOpen size={20} weight="bold" />
              </button>}
              <button type="button" className="category-row-action remove" onClick={() => removePath(key)} disabled={visibleKeys.length <= 1} title={`删除${label}`} aria-label={`删除${label}`}>
                <MinusCircle size={21} weight="bold" />
              </button>
            </div>
          );
        })}
        <div className="category-custom-editor">
          <label>
            <span>新增自定义分类</span>
            <input
              value={customKey}
              placeholder="例如：短剧 或 short_drama"
              aria-label="自定义分类标识"
              onChange={(event) => { setCustomKey(event.target.value); setCustomError(""); }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addCustomPath();
                }
              }}
            />
          </label>
          <button type="button" className="category-add" onClick={addCustomPath}>
            <PlusCircle size={20} weight="bold" />
            <span>添加</span>
          </button>
          {customError && <small role="alert">{customError}</small>}
        </div>
      </div>
    </>
  );
}
