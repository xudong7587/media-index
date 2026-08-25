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

export function SettingsToggle({
  label,
  help,
  value,
  onChange,
  trueLabel = "开",
  falseLabel = "关",
  disabled = false,
  busy = false,
}: {
  label: string;
  help?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  trueLabel?: string;
  falseLabel?: string;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  return (
    <div className="settings-field">
      <span className="settings-label">
        {label}
        {help && (
          <span className="inline-help-wrap">
            <button type="button" className="inline-help" aria-label={`${label}说明`} aria-expanded={helpOpen} onClick={() => setHelpOpen((current) => !current)} onBlur={() => window.setTimeout(() => setHelpOpen(false), 120)}>
              <Question size={15} weight="bold" />
            </button>
            <span className={`inline-help-popover ${helpOpen ? "open" : ""}`} role="tooltip">{help}</span>
          </span>
        )}
      </span>
      <div className="toggle-group" role="group" aria-label={label}>
        <button type="button" className={value ? "active" : ""} onClick={() => onChange(true)} disabled={disabled}>
          {busy && value && <span className="spinner" aria-hidden="true" />}
          {trueLabel}
        </button>
        <button type="button" className={!value ? "active" : ""} onClick={() => onChange(false)} disabled={disabled}>
          {busy && !value && <span className="spinner" aria-hidden="true" />}
          {falseLabel}
        </button>
      </div>
    </div>
  );
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

export function SettingsInput({ label, name, value, saved, help, helpTooltip, secret, placeholder, showSavedValue, onChange, onReveal, action, result }: {
  label: string;
  name: string;
  value: string;
  saved: boolean;
  help?: string;
  helpTooltip?: string;
  secret?: boolean;
  placeholder?: string;
  showSavedValue?: boolean;
  onChange: (key: string, value: string) => void;
  onReveal?: (value: string) => void;
  action?: React.ReactNode;
  result?: { ok: boolean; message: string } | null;
}) {
  const [secretVisible, setSecretVisible] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState("");
  const savedPlaceholder = savedInputPlaceholder(name, placeholder, showSavedValue ?? !secret, Boolean(secret));
  async function toggleSecretVisibility() {
    if (secretVisible) {
      setSecretVisible(false);
      setRevealedSecret("");
      return;
    }
    if (!value && saved) {
      try {
        const result = await api.configSecret(name);
        setRevealedSecret(result.value);
        onReveal?.(result.value);
      } catch {
        setRevealedSecret("");
      }
    }
    setSecretVisible(true);
  }
  return (
    <div className="settings-field">
      <span className="settings-label">{label}{helpTooltip && <InlineHelp label={label} text={helpTooltip} />}{help && <small className="settings-field-help">{help}</small>}</span>
      <div className="settings-input-content">
        <div className="settings-input-action">
          <div className={secret ? "settings-secret-input" : "settings-plain-input"}>
            <input aria-label={label} type={secret && !secretVisible ? "password" : "text"} value={value || revealedSecret} placeholder={saved ? savedPlaceholder : placeholder || "未配置"} onChange={(event) => { setRevealedSecret(""); onChange(name, event.target.value); }} />
            {secret && <button type="button" className="settings-secret-visibility" aria-label={secretVisible ? `隐藏${label}` : `显示${label}`} title={secretVisible ? "隐藏" : "显示"} onClick={() => void toggleSecretVisibility()}>{secretVisible ? <EyeSlash size={19} /> : <Eye size={19} />}</button>}
          </div>
          {action}
        </div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </div>
    </div>
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

  function update(next: string[]) {
    onChange("quality_priority_keywords", next.join("\n"));
  }

  function remove(index: number) {
    if (configured.length <= 1) return;
    update(configured.filter((_item, itemIndex) => itemIndex !== index));
  }

  function add() {
    const value = window.prompt("输入自定义质量关键词，例如 1080P REMUX")?.trim();
    if (value && !configured.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) update([...configured, value]);
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
        <button type="button" className="quality-priority-add" onClick={add} title="添加自定义质量关键词"><PlusCircle size={19} weight="bold" /><span>自定义</span></button>
      </div>
      <p className="settings-help">默认包含：4K 原盘、4K DV、4K HDR、4K SDR、4K、1080P HDR、1080P、720P、WEB-DL、WEBRip、SDR。匹配会兼容 2160P、Remux、杜比视界等常见写法。</p>
    </div>
  );
}

export function InlineHelp({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-help-wrap">
      <button type="button" className="inline-help" aria-label={`${label}说明`} aria-expanded={open} onClick={() => setOpen((current) => !current)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}>
        <Question size={15} weight="bold" />
      </button>
      <span className={`inline-help-popover ${open ? "open" : ""}`} role="tooltip">{text}</span>
    </span>
  );
}

export function savedInputPlaceholder(name: string, placeholder = "", showSavedValue = false, secret = false) {
  if (!showSavedValue || !placeholder) return "已保存，如需修改请重新填写";
  const shouldMask = secret || /(token|cookie|secret|api_key|password)/i.test(name);
  if (shouldMask) return "已保存，如需修改请重新填写";
  return `${placeholder}，如需修改请重新填写`;
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
        <button type="button" className="category-add" onClick={() => {
          const key = window.prompt("自定义分类标识（如 documentary）")?.trim();
          if (key && /^[a-zA-Z0-9_-]+$/.test(key) && !visibleKeys.includes(key)) {
            setVisibleKeys((current) => [...current, key]);
            updatePath(key, `/${key}`);
          }
        }}>
          <PlusCircle size={22} weight="bold" />
          <span>自定义分类</span>
        </button>
      </div>
    </>
  );
}
