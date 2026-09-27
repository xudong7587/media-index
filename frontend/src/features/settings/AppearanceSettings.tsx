import { Check, Palette, X } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

export type Theme = "light" | "dark";
const accents = [
  { id: "blue", name: "晴蓝", light: "#315cbe", dark: "#9dbbff" },
  { id: "green", name: "松绿", light: "#187052", dark: "#80d5b2" },
  { id: "violet", name: "鸢紫", light: "#7146b5", dark: "#c4a7f4" },
  { id: "rose", name: "莓红", light: "#ac3b66", dark: "#f2a4c0" },
  { id: "amber", name: "琥珀", light: "#94600c", dark: "#ebc078" },
  { id: "slate", name: "石墨", light: "#526174", dark: "#b2c1d4" },
] as const;
type Accent = typeof accents[number]["id"];

function readPreference(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function savePreference(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* Session choice still works when storage is unavailable. */ }
}
function validAccent(value: string | null): Accent {
  return accents.find((accent) => accent.id === value)?.id ?? "blue";
}
function applyAccent(accent: Accent) {
  const palette = accents.find((item) => item.id === accent)!;
  const root = document.documentElement;
  root.dataset.accent = accent;
  root.style.setProperty("--accent-light", palette.light);
  root.style.setProperty("--accent-dark", palette.dark);
}

// Apply before React's first render, including the login screen.
document.documentElement.dataset.theme = readPreference("mi-theme") === "dark" ? "dark" : "light";
applyAccent(validAccent(readPreference("mi-accent")));

export function useAppearanceTheme() {
  const [theme, setTheme] = useState<Theme>(() => readPreference("mi-theme") === "dark" ? "dark" : "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    savePreference("mi-theme", theme);
  }, [theme]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === "mi-theme" || event.key === null) setTheme(readPreference("mi-theme") === "dark" ? "dark" : "light");
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return [theme, setTheme] as const;
}

export function AppearanceSettings({ theme, onThemeChange }: { theme: Theme; onThemeChange: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [accent, setAccent] = useState<Accent>(() => validAccent(readPreference("mi-accent")));
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === "mi-accent" || event.key === null) {
        const next = validAccent(readPreference("mi-accent"));
        setAccent(next);
        applyAccent(next);
      }
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return <>
    <button type="button" className="icon appearance-trigger" title="外观与主题色" aria-label="外观与主题色" onClick={() => dialog.current?.showModal()}><Palette size={19} /></button>
    <dialog ref={dialog} className="appearance-dialog" aria-labelledby="appearance-title" onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <div className="appearance-content">
        <header><div><h2 id="appearance-title">外观与主题色</h2><p>选择看着舒服的颜色，即时生效。</p></div><button type="button" className="icon" aria-label="关闭外观设置" onClick={() => dialog.current?.close()}><X size={18} /></button></header>
        <fieldset><legend>显示模式</legend><div className="appearance-modes">{(["light", "dark"] as const).map((mode) => <button type="button" key={mode} aria-pressed={theme === mode} onClick={() => { if (theme !== mode) onThemeChange(); }}>{mode === "light" ? "浅色" : "深色"}{theme === mode && <Check size={16} />}</button>)}</div></fieldset>
        <fieldset><legend>主题色</legend><div className="appearance-swatches">{accents.map((item) => <button type="button" key={item.id} aria-pressed={accent === item.id} onClick={() => { setAccent(item.id); applyAccent(item.id); savePreference("mi-accent", item.id); }} style={{ "--swatch": theme === "dark" ? item.dark : item.light } as CSSProperties}><span className="appearance-swatch" />{item.name}{accent === item.id && <Check size={16} />}</button>)}</div></fieldset>
        <div className="appearance-preview"><span>效果预览</span><strong>清晰的内容，适度的强调</strong><p>文字、卡片和操作保持一致，成功、警告与错误仍使用各自的状态色。</p><span className="appearance-preview-action">主要操作</span></div>
        <footer>自动保存在当前浏览器</footer>
      </div>
    </dialog>
  </>;
}
