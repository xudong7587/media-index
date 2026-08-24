import {
  ArrowsLeftRight,
  Binoculars,
  Cloud,
  GithubLogo,
  List,
  Moon,
  PlayCircle,
  SignOut,
  SidebarSimple,
  SlidersHorizontal,
  Sun,
  TelevisionSimple,
  VideoCamera,
  X,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useState } from "react";

import { AppRoute, PrimaryPage } from "./routes";

type Theme = "light" | "dark";

const navigation = [
  { page: "discover", label: "发现", hint: "探索与搜索", icon: Binoculars },
  { page: "subscriptions", label: "订阅与追更", hint: "愿望与补集", icon: TelevisionSimple },
  { page: "workspace", label: "网盘工作台", hint: "连接、规则与任务", icon: Cloud },
  { page: "cross-cloud", label: "跨盘转存", hint: "OpenList 复制", icon: ArrowsLeftRight },
  { page: "strm", label: "STRM 与 302", hint: "媒体库播放", icon: PlayCircle },
  { page: "media-server", label: "媒体服务器", hint: "Emby 数据看板", icon: VideoCamera },
  { page: "system", label: "全局设置", hint: "服务与交互", icon: SlidersHorizontal },
] satisfies Array<{ page: PrimaryPage; label: string; hint: string; icon: typeof Binoculars }>;

const pageMeta: Record<PrimaryPage, { label: string; context: string }> = {
  discover: { label: "发现", context: "资源入口" },
  subscriptions: { label: "订阅与追更", context: "持续追踪" },
  workspace: { label: "网盘工作台", context: "云端执行" },
  "cross-cloud": { label: "跨盘转存", context: "OpenList 执行" },
  strm: { label: "STRM 与 302", context: "媒体播放" },
  "media-server": { label: "媒体服务器", context: "Emby 看板" },
  system: { label: "全局设置", context: "系统服务" },
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("mi-sidebar-collapsed") === "true",
  );

  useEffect(() => {
    localStorage.setItem("mi-sidebar-collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`} data-page={route.page}>
      <aside className="app-sidebar">
        <div className="sidebar-header">
          <button className="wordmark" onClick={() => { onNavigate({ page: "discover" }); setMobileNavOpen(false); }}>
            <img className="brand-logo" src="/assets/media-index-icon.png" alt="Media Index" />
            <span><strong>Media Index</strong><small>媒体资源中枢</small></span>
          </button>
          <button
            type="button"
            className="sidebar-collapse-toggle"
            aria-label={sidebarCollapsed ? "展开工作区导航" : "收起工作区导航"}
            title={sidebarCollapsed ? "打开侧栏" : "关闭侧栏"}
            onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
          >
            <SidebarSimple size={22} weight="regular" />
          </button>
        </div>
        <div className="mobile-current-page" aria-hidden="true"><small>{current.context}</small><strong>{current.label}</strong></div>
        <nav id="primary-navigation" className={mobileNavOpen ? "mobile-open" : ""} aria-label="主导航">
          {navigation.map(({ page, label, hint, icon: Icon }) => (
            <button key={page} className={route.page === page ? "active" : ""} aria-label={label} title={label} onClick={() => { onNavigate({ page }); setMobileNavOpen(false); }}>
              <Icon size={20} weight={route.page === page ? "fill" : "regular"} />
              <span><strong>{label}</strong><small>{hint}</small></span>
            </button>
          ))}
        </nav>
        <footer className="sidebar-footer">
          <div className="sidebar-user"><span>{user.slice(0, 1).toUpperCase()}</span><div><strong>{user}</strong><small>本地工作区</small></div></div>
          <a
            className="icon"
            href="https://github.com/xudong7587/media-index"
            target="_blank"
            rel="noreferrer"
            title="打开 GitHub 仓库"
            aria-label="打开 Media Index GitHub 仓库"
          >
            <GithubLogo size={18} weight="fill" />
          </a>
          <button className="icon" onClick={onThemeChange} title="切换主题" aria-label="切换主题">
            {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button className="icon" onClick={onLogout} title="退出" aria-label="退出登录">
            <SignOut size={18} />
          </button>
          <small className="sidebar-version">MediaIndex v{version}</small>
        </footer>
        <button
          type="button"
          className="mobile-nav-toggle"
          aria-label={mobileNavOpen ? "关闭主导航" : "打开主导航"}
          aria-controls="primary-navigation"
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen((open) => !open)}
        >
          {mobileNavOpen ? <X size={22} /> : <List size={22} />}
        </button>
      </aside>
      <div className="app-workspace">
        <header className="workspace-chrome">
          <div className="workspace-location"><span>{current.context}</span><strong>{current.label}</strong></div>
          <div className="workspace-actions">
            <div className="workspace-status"><span className="status-dot" />本地服务运行中</div>
            <div className="top-actions">{activity}</div>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
