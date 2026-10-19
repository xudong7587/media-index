import { Check, Palette, X } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";

let storagePrefix = "sunny-ui";
function preferenceKey(key: string) { return key.replace(/^mi/, storagePrefix); }

export type Theme = "light" | "dark";
export const accents = [
  { id: "blue", name: "晴蓝", light: "#376bd8", dark: "#9dbbff" },
  { id: "green", name: "松绿", light: "#188466", dark: "#80d5b2" },
  { id: "violet", name: "鸢紫", light: "#8855cc", dark: "#c4a7f4" },
  { id: "rose", name: "莓红", light: "#c34278", dark: "#f2a4c0" },
  { id: "amber", name: "琥珀", light: "#b27a16", dark: "#ebc078" },
  { id: "slate", name: "石墨", light: "#61758f", dark: "#b2c1d4" },
  { id: "celadon", name: "青瓷", light: "#2f7f76", dark: "#8fd6c9" },
  { id: "brick", name: "砖窑", light: "#a8433a", dark: "#eda79e" },
  { id: "mustard", name: "芥末", light: "#8f7a12", dark: "#ddc66a" },
  { id: "indigo", name: "靛蓝", light: "#3b4fa8", dark: "#a9b6f0" },
  { id: "catppuccin", name: "奶霜花园", light: "#c14f7c", dark: "#f0acc7", secondary: "#179299", tertiary: "#d20f39", secondaryDark: "#94e2d5", tertiaryDark: "#f5c2e7" },
  { id: "nord", name: "北境极光", light: "#427fa4", dark: "#88c0d0", secondary: "#5e678d", tertiary: "#42776c", secondaryDark: "#b48ead", tertiaryDark: "#a3be8c" },
  { id: "iris", name: "鸢尾暮色", light: "#7958c8", dark: "#b7a5ff", secondary: "#b34379", tertiary: "#22778a", secondaryDark: "#f3a6ce", tertiaryDark: "#79d1de" },
  { id: "coast", name: "海盐日落", light: "#14869a", dark: "#79d5e5", secondary: "#b64d38", tertiary: "#866519", secondaryDark: "#ffaf98", tertiaryDark: "#edcf86" },
  { id: "macaron", name: "马卡龙", light: "#329383", dark: "#a7dfd0", secondary: "#9461ac", tertiary: "#b35a70", secondaryDark: "#dab6ef", tertiaryDark: "#f4bacb" },
  { id: "peach", name: "蜜桃乌龙", light: "#c16648", dark: "#f5b79d", secondary: "#7e6541", tertiary: "#6b7d49", secondaryDark: "#e2cb9d", tertiaryDark: "#c8d7a7" },
  { id: "lavender", name: "蓝调花雾", light: "#467fb2", dark: "#a5c7e8", secondary: "#7758a6", tertiary: "#9b586e", secondaryDark: "#c9b4ef", tertiaryDark: "#e8b4c7" },
  { id: "forest", name: "雨后花园", light: "#3d895f", dark: "#9bd0af", secondary: "#8a6532", tertiary: "#625eaa", secondaryDark: "#dfc392", tertiaryDark: "#bdb8ef" },
  { id: "honey", name: "蜂蜜麦田", light: "#a17a24", dark: "#e4c278", secondary: "#397976", tertiary: "#ad6556", secondaryDark: "#9dcfcb", tertiaryDark: "#e5b0a3" },
  { id: "ruby", name: "红茶玫瑰", light: "#c04757", dark: "#ee9aa5", secondary: "#567647", tertiary: "#9b742e", secondaryDark: "#b5cda4", tertiaryDark: "#dfc48a" },
  { id: "deepsea", name: "深海鎏金", light: "#1d6f8b", dark: "#7fd2e8", secondary: "#b4892f", tertiary: "#4c5d8a", secondaryDark: "#ecd08a", tertiaryDark: "#a9b6e0" },
  { id: "lava", name: "暮色熔岩", light: "#b4465e", dark: "#f2a5b2", secondary: "#7a4c93", tertiary: "#d97a3d", secondaryDark: "#c3a6ea", tertiaryDark: "#f6c39a" },
  { id: "cedar", name: "薄荷雪松", light: "#2e8b74", dark: "#9fe0c9", secondary: "#8fa06a", tertiary: "#c9a227", secondaryDark: "#cfd9a8", tertiaryDark: "#ecd08a" },
  { id: "mist", name: "海雾晨光", light: "#4f7fa8", dark: "#a9cbe8", secondary: "#8fb9c9", tertiary: "#d9a98a", secondaryDark: "#cfe6ec", tertiaryDark: "#f0cfb4" },
  { id: "oasis", name: "沙漠绿洲", light: "#b07a2e", dark: "#eccd94", secondary: "#4e8a6b", tertiary: "#8a5a3c", secondaryDark: "#a8d4b6", tertiaryDark: "#d5ad8c" },
  { id: "nightviolet", name: "紫罗兰夜", light: "#6c4ab6", dark: "#bfa6f5", secondary: "#c05a8e", tertiary: "#2f8fa8", secondaryDark: "#f0a8c2", tertiaryDark: "#8fd8e6" },
] as const;
export const materials = [
  { id: "default", name: "清晰默认", description: "轻盈、克制，专注内容" },
  { id: "paper", name: "纸页档案", description: "暖纸、细线，安静阅读" },
  { id: "aurora", name: "极光玻璃", description: "流光、渐变，柔和层次" },
  { id: "soft", name: "柔软浮雕", description: "柔光、浅浮雕，温润触感" },
  { id: "outline", name: "精致描边", description: "纤细轮廓，利落层次" },
  { id: "duotone", name: "双色渐层", description: "色彩交融，轻盈空间" },
  { id: "satin", name: "缎光瓷面", description: "细腻釉光，柔亮曲面" },
  { id: "glass", name: "iOS 玻璃", description: "磨砂、亮边，悬浮质感" },
  { id: "linen", name: "亚麻织纹", description: "斜向织纹，哑光无釉" },
  { id: "frosted", name: "雾面玻璃", description: "更雾更厚，整块贴在墙上" },
  { id: "metal", name: "拉丝金属", description: "横向拉丝、硬高光、冷银" },
  { id: "clay", name: "陶土哑光", description: "暖陶土与颗粒，影子里没有高光" },
  { id: "marble", name: "大理石", description: "石纹与釉面，冷白" },
  { id: "neon", name: "霓虹暗夜", description: "深色面板，边缘发光" },
  { id: "cutout", name: "纸片拼贴", description: "硬投影与实边线，像贴上去的" },
  { id: "mesh", name: "雾面色场", description: "页面很彩色，卡片退成哑光面" },
] as const;
type Material = typeof materials[number]["id"];
const LEGACY_MATERIAL_IDS = ["default", "paper", "aurora", "soft", "outline", "duotone", "satin", "glass"];
const legacyMaterials = materials.filter((item) => LEGACY_MATERIAL_IDS.includes(item.id));
function validMaterial(value: string | null): Material { if (value === "blocks") return "satin"; return materials.find((item) => item.id === value)?.id ?? "default"; }
function applyMaterial(material: Material) { if (typeof document === "undefined") return; document.documentElement.dataset.material = material; }

type Accent = typeof accents[number]["id"];
const LEGACY_ACCENT_IDS = ["blue", "green", "violet", "rose", "amber", "slate", "catppuccin", "nord", "iris", "coast", "macaron", "peach", "lavender", "forest", "honey", "ruby"];
const legacyAccents = accents.filter((item) => LEGACY_ACCENT_IDS.includes(item.id));

export type Corner = "tight" | "default" | "round";
const corners = [
  { id: "tight", name: "紧致" },
  { id: "default", name: "标准" },
  { id: "round", name: "圆润" },
] as const;
function validCorner(value: string | null): Corner { return value === "tight" || value === "round" ? value : "default"; }
function applyCorner(corner: Corner) { if (typeof document === "undefined") return; document.documentElement.dataset.corner = corner; }

function readPreference(key: string): string | null {
  try { return localStorage.getItem(preferenceKey(key)); } catch { return null; }
}
function savePreference(key: string, value: string) {
  try { localStorage.setItem(preferenceKey(key), value); } catch { /* Session choice still works when storage is unavailable. */ }
}
function validAccent(value: string | null): Accent {
  return accents.find((accent) => accent.id === value)?.id ?? "blue";
}
function applyAccent(accent: Accent) {
  const palette = accents.find((item) => item.id === accent)!;
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.accent = accent;
  const multi = "secondary" in palette;
  root.dataset.palette = multi ? "multi" : "single";
  root.style.setProperty("--secondary-light", multi ? palette.secondary : palette.light);
  root.style.setProperty("--secondary-dark", multi ? palette.secondaryDark : palette.dark);
  root.style.setProperty("--tertiary-light", multi ? palette.tertiary : palette.light);
  root.style.setProperty("--tertiary-dark", multi ? palette.tertiaryDark : palette.dark);
  const channels = palette.light.slice(1).match(/.{2}/g)!.map((hex) => { const value = parseInt(hex, 16) / 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; });
  const luminance = channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  root.style.setProperty("--accent-light-ink", 1.05 / (luminance + .05) >= 4.5 ? "#ffffff" : "#17202e");
  root.style.setProperty("--accent-light", palette.light);
  root.style.setProperty("--accent-dark", palette.dark);
}

function readLegacy(): boolean { return readPreference("mi-legacy-appearance") === "true"; }
function applyLegacy(legacy: boolean) { if (typeof document === "undefined") return; document.documentElement.dataset.appearance = legacy ? "classic" : "modern"; }

/** Call before mounting React to give each application its own preference keys. */
export function configureAppearance(options: { storagePrefix?: string } = {}) {
  storagePrefix = options.storagePrefix || "sunny-ui";
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = readPreference("mi-theme") === "dark" ? "dark" : "light";
  applyLegacy(readLegacy());
  applyCorner(validCorner(readPreference("mi-corner")));
  applyAccent(validAccent(readPreference("mi-accent")));
  applyMaterial(validMaterial(readPreference("mi-material")));
}
configureAppearance({ storagePrefix: "mi" });

export function useAppearanceTheme() {
  const [theme, setTheme] = useState<Theme>(() => readPreference("mi-theme") === "dark" ? "dark" : "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    savePreference("mi-theme", theme);
  }, [theme]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === preferenceKey("mi-theme") || event.key === null) setTheme(readPreference("mi-theme") === "dark" ? "dark" : "light");
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return [theme, setTheme] as const;
}

export function AppearancePicker({ theme, onThemeChange }: { theme: Theme; onThemeChange: () => void }) {
  const [material, setMaterial] = useState<Material>(() => validMaterial(readPreference("mi-material")));
  const [accent, setAccent] = useState<Accent>(() => validAccent(readPreference("mi-accent")));
  const [corner, setCorner] = useState<Corner>(() => validCorner(readPreference("mi-corner")));
  const [legacy, setLegacy] = useState<boolean>(readLegacy);
  const titleId = useId();
  useEffect(() => { applyMaterial(material); }, [material]);
  useEffect(() => { applyAccent(accent); }, [accent]);
  useEffect(() => { applyLegacy(legacy); savePreference("mi-legacy-appearance", String(legacy)); }, [legacy]);
  useEffect(() => { applyCorner(legacy ? "default" : corner); }, [corner, legacy]);
  const dialog = useRef<HTMLDialogElement>(null);
  const visibleAccents = legacy ? legacyAccents : accents;
  const visibleMaterials = legacy ? legacyMaterials : materials;
  function chooseLegacy(next: boolean) {
    setLegacy(next);
    if (!next) return;
    if (!legacyMaterials.some((item) => item.id === material)) { setMaterial("soft"); savePreference("mi-material", "soft"); }
    if (!legacyAccents.some((item) => item.id === accent)) { setAccent("blue"); savePreference("mi-accent", "blue"); }
  }
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === preferenceKey("mi-material") || event.key === null) { const next = validMaterial(readPreference("mi-material")); setMaterial(next); applyMaterial(next); }
      if (event.key === preferenceKey("mi-accent") || event.key === null) {
        const next = validAccent(readPreference("mi-accent"));
        setAccent(next);
        applyAccent(next);
      }
      if (event.key === preferenceKey("mi-corner") || event.key === null) { const next = validCorner(readPreference("mi-corner")); setCorner(next); applyCorner(next); }
      if (event.key === preferenceKey("mi-legacy-appearance") || event.key === null) setLegacy(readLegacy());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return <>
    <button type="button" className="icon appearance-trigger" title="外观与主题色" aria-label="外观与主题色" onClick={() => dialog.current?.showModal()}><Palette size={19} /><span className="appearance-trigger-label">外观</span></button>
    <dialog ref={dialog} className="appearance-dialog" aria-labelledby={titleId} onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <div className="appearance-content">
        <header><div><h2 id={titleId}>外观与主题色</h2><p>{legacy ? "经典外观：8 种质感与 15 套配色。" : "色彩 × 质感 × 圆角 × 明暗，自由组合，即时生效。"}</p></div><button type="button" className="icon" aria-label="关闭外观设置" onClick={() => dialog.current?.close()}><X size={18} /></button></header>
        <fieldset><legend>外观版本</legend><div className="appearance-modes">{([false, true] as const).map((isClassic) => <button type="button" key={String(isClassic)} aria-pressed={legacy === isClassic} onClick={() => { if (legacy !== isClassic) chooseLegacy(isClassic); }}>{isClassic ? "经典外观" : "新版外观"}{legacy === isClassic && <Check size={16} />}</button>)}</div></fieldset>
        <fieldset><legend>显示模式</legend><div className="appearance-modes">{(["light", "dark"] as const).map((mode) => <button type="button" key={mode} aria-pressed={theme === mode} onClick={() => { if (theme !== mode) onThemeChange(); }}>{mode === "light" ? "浅色" : "深色"}{theme === mode && <Check size={16} />}</button>)}</div></fieldset>
        {!legacy && <fieldset><legend>圆角</legend><div className="appearance-modes">{corners.map((item) => <button type="button" key={item.id} aria-pressed={corner === item.id} onClick={() => { setCorner(item.id); applyCorner(item.id); savePreference("mi-corner", item.id); }}>{item.name}{corner === item.id && <Check size={16} />}</button>)}</div></fieldset>}
        {([false, true] as const).map((multi) => <fieldset key={String(multi)}><legend>{multi ? "多色搭配" : "主题色"}</legend><div className="appearance-swatches">{visibleAccents.filter((item) => ("secondary" in item) === multi).map((item) => <button type="button" key={item.id} aria-pressed={accent === item.id} onClick={() => { setAccent(item.id); applyAccent(item.id); savePreference("mi-accent", item.id); }}><span className={multi ? "appearance-color-wheel" : "appearance-color-strip"} aria-hidden="true" style={"secondary" in item ? { background: `conic-gradient(from -90deg, ${theme === "dark" ? item.dark : item.light}, ${theme === "dark" ? item.secondaryDark : item.secondary} 33%, ${theme === "dark" ? item.tertiaryDark : item.tertiary} 67%, ${theme === "dark" ? item.dark : item.light})` } : undefined}>{[theme === "dark" ? item.dark : item.light, ...("secondary" in item ? [theme === "dark" ? item.secondaryDark : item.secondary, theme === "dark" ? item.tertiaryDark : item.tertiary] : [])].map((color, index) => <i key={index} style={{ background: color } as CSSProperties} />)}</span>{item.name}{accent === item.id && <Check size={16} />}</button>)}</div></fieldset>)}
        <fieldset><legend>界面质感</legend><div className="appearance-materials">{visibleMaterials.map((item) => <button type="button" key={item.id} aria-pressed={material === item.id} onClick={() => { setMaterial(item.id); applyMaterial(item.id); savePreference("mi-material", item.id); }}><span className={`appearance-mini appearance-mini-${item.id}`} aria-hidden="true"><i /><i /><i /></span><span><strong>{item.name}</strong><small>{item.description}</small></span>{material === item.id && <Check size={16} />}</button>)}</div></fieldset>
        <div className="appearance-preview"><span>组合预览 · {visibleMaterials.find((item) => item.id === material)?.name}</span><strong>清晰的内容，适度的强调</strong><p>文字、卡片和操作保持一致，成功、警告与错误仍使用各自的状态色。</p><div className="appearance-preview-bars" aria-hidden="true"><i /><i /><i /></div><span className="appearance-preview-action">主要操作</span></div>
        <footer>自动保存在当前浏览器{legacy ? " · 当前为经典外观" : ""}</footer>
      </div>
    </dialog>
  </>;
}
