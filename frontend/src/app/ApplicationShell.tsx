import {
  ArrowsLeftRight,
  Binoculars,
  BookOpenText,
  CaretRight,
  Cloud,
  GithubLogo,
  MagnifyingGlass,
  Moon,
  PlayCircle,
  SignOut,
  SlidersHorizontal,
  Sun,
  TelevisionSimple,
  VideoCamera,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useState } from "react";

import { AppRoute, PrimaryPage } from "./routes";
import { AppearanceSettings } from "../features/settings/AppearanceSettings";


type Theme = "light" | "dark";
type NavItem = { page: PrimaryPage; label: string; hint: string; icon: typeof Binoculars };

const workspaceNav: NavItem[] = [
  { page: "discover", label: "发现", hint: "探索与搜索", icon: Binoculars },
  { page: "subscriptions", label: "订阅与追更", hint: "愿望与补集", icon: TelevisionSimple },
  { page: "workspace", label: "网盘工作台", hint: "连接、规则与任务", icon: Cloud },
  { page: "cross-cloud", label: "跨盘转存", hint: "夸克 → 115 补齐", icon: ArrowsLeftRight },
  { page: "strm", label: "STRM 与 302", hint: "媒体库播放", icon: PlayCircle },
  { page: "media-server", label: "媒体服务器", hint: "Emby 数据看板", icon: VideoCamera },
];

const systemNav: NavItem[] = [
  { page: "system", label: "全局设置", hint: "服务与交互", icon: SlidersHorizontal },
  { page: "guide", label: "使用手册", hint: "完整使用说明", icon: BookOpenText },
];

const pageMeta: Record<PrimaryPage, { label: string; context: string }> = {
  discover: { label: "发现", context: "资源入口" },
  subscriptions: { label: "订阅与追更", context: "持续追踪" },
  workspace: { label: "网盘工作台", context: "云端执行" },
  "cross-cloud": { label: "跨盘转存", context: "跨盘补齐" },
  strm: { label: "STRM 与 302", context: "媒体播放" },
  "media-server": { label: "媒体服务器", context: "Emby 看板" },
  system: { label: "全局设置", context: "系统服务" },
  guide: { label: "使用手册", context: "帮助中心" },
};

export function ApplicationShell({
  user,
  version,
  theme,
  route,
  onNavigate,
  onThemeChange,
  onLogout,
  activity,
  children,
}: {
  user: string;
  version: string;
  theme: Theme;
  route: AppRoute;
  onNavigate: (route: AppRoute) => void;
  onThemeChange: () => void;
  onLogout: () => void;
  activity: ReactNode;
  children: ReactNode;
}) {
  const current = pageMeta[route.page];
  const [menuOpen, setMenuOpen] = useState(false);
  const [appearance, setAppearance] = useState<Record<string, string>>({});

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setAppearance({
      "data-theme": root.dataset.theme || "light",
      "data-material": root.dataset.material || "default",
      "data-accent": root.dataset.accent || "blue",
      "data-corner": root.dataset.corner || "default",
      "data-palette": root.dataset.palette || "single",
    });
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme", "data-material", "data-accent", "data-corner", "data-palette"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => setMenuOpen(false), [route.page, route.section]);

  const navButton = (item: NavItem) => {
    const Icon = item.icon;
    const active = route.page === item.page;
    return (
      <button
        key={item.page}
        type="button"
        className={`nav-item${active ? " active" : ""}`}
        aria-current={active ? "page" : undefined}
        onClick={() => onNavigate({ page: item.page })}
      >
        <Icon className="ic" size={20} weight={active ? "fill" : "regular"} />
        <span className="label"><strong>{item.label}</strong><small>{item.hint}</small></span>
        <CaretRight className="ic ic-sm go" size={13} aria-hidden />
      </button>
    );
  };

  return (
    <div className={`app mi-shell mi-preview sunny-workbench${menuOpen ? " menu-open" : ""}`} data-page={route.page} {...appearance}>
      <aside className="sidebar">
        <button type="button" className="brand" onClick={() => onNavigate({ page: "discover" })}>
          <span className="brand-mark original"><svg viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="miBrandTile" x2="1" y2="1"><stop stopColor="#d886a6" /><stop offset="1" stopColor="#c14f7c" /></linearGradient></defs><rect width="48" height="48" rx="13" fill="url(#miBrandTile)" /><g transform="translate(9.4 10.2)" fill="none" stroke="#352333" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h21v3M4 12v12a2 2 0 0 0 2 2h7M3 7l20-5 1.2 4.8-20 5Z" /><path d="m8 5.8 3.4 4.2m4-6 3.4 4.2" /><circle cx="21" cy="22" r="6" /><path d="m25.4 26.4 4.6 4.1" /></g></svg></span>
          <span className="brand-text"><strong>MediaIndex</strong><small>给好故事，一个家</small></span>
        </button>

        <nav className="nav" aria-label="主导航">
          <span className="nav-label">工作区</span>
          {workspaceNav.map(navButton)}
          <span className="nav-label">系统</span>
          {systemNav.map(navButton)}
        </nav>

        <div className="sidebar-spacer" />
        <button type="button" className="side-note" onClick={() => { onNavigate({ page: "discover" }); window.setTimeout(() => document.querySelector<HTMLInputElement>(".search input, input[type='search']")?.focus(), 120); }}>
          <span className="hint-row"><MagnifyingGlass className="ic ic-sm" size={14} /><strong>快速检索</strong></span>
          在发现页按 <span className="kbd">/</span> 直接聚焦搜索框，支持电影、剧集与综艺。
        </button>
        <div className="side-foot">
          <div className="avatar">{user.slice(0, 1).toUpperCase()}</div>
          <div className="who"><strong>{user}</strong><small>本地工作区</small></div>
          <a className="icon-btn" href="https://github.com/xudong7587/media-index" target="_blank" rel="noreferrer" title="打开 GitHub 仓库" aria-label="打开 GitHub 仓库">
            <GithubLogo size={16} weight="fill" />
          </a>
          <button type="button" className="icon-btn" onClick={onThemeChange} title="切换深浅" aria-label="切换深浅">
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
          </button>
          <button type="button" className="icon-btn" onClick={onLogout} title="退出" aria-label="退出登录">
            <SignOut size={16} />
          </button>
        </div>
        <small className="version">MediaIndex v{version} · 本地运行</small>
      </aside>
      <div className={`menu-backdrop${menuOpen ? " open" : ""}`} onClick={() => setMenuOpen(false)} />

      <div className="workspace">
        <header className="topbar">
          <div className="crumb">
            <button type="button" className="icon-btn menu-btn" aria-label="打开菜单" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
              <svg className="ic ic-sm" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
            </button>
            <span className="mobile-brand"><svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="13" fill="#c14f7c" /><g transform="translate(9.4 10.2)" fill="none" stroke="#352333" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h21v3M4 12v12a2 2 0 0 0 2 2h7M3 7l20-5 1.2 4.8-20 5Z" /><circle cx="21" cy="22" r="6" /><path d="m25.4 26.4 4.6 4.1" /></g></svg></span>
            <span>{current.context}</span>
            <CaretRight className="ic" size={14} aria-hidden />
            <strong>{current.label}</strong>
          </div>
          <div className="top-actions">
            <span className="status-chip"><i />本地服务运行中</span>
            <AppearanceSettings theme={theme} onThemeChange={onThemeChange} />
            {activity}
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
