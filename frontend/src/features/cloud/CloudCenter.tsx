import { ArrowsLeftRight, Broadcast, CloudCheck, LinkSimple, ListChecks } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api, ConfigStatus } from "../../lib/api";
import { QuarkReadOnlySettings } from "../settings/QuarkReadOnlySettings";
import { CrossCloudTransferCenter } from "./CrossCloudTransferCenter";
import { ChannelWorkspace } from "./ChannelWorkspace";

type CloudSection = "overview" | "connections" | "verification" | "transfers" | "channels";

const sections: Array<{ key: CloudSection; label: string; icon: typeof CloudCheck }> = [
  { key: "overview", label: "总览", icon: CloudCheck },
  { key: "connections", label: "网盘账号", icon: LinkSimple },
  { key: "verification", label: "资源验真", icon: ListChecks },
  { key: "transfers", label: "转存任务", icon: ArrowsLeftRight },
  { key: "channels", label: "频道来源", icon: Broadcast },
];

export function CloudCenter({ initialSection = "overview" }: { initialSection?: CloudSection }) {
  const [section, setSection] = useState<CloudSection>(initialSection);
  const [config, setConfig] = useState<ConfigStatus | null>(null);

  async function refresh() {
    setConfig(await api.config());
  }

  useEffect(() => {
    void refresh().catch(() => setConfig(null));
    window.addEventListener("mediaindex:providers-changed", refresh);
    return () => window.removeEventListener("mediaindex:providers-changed", refresh);
  }, []);

  useEffect(() => setSection(initialSection), [initialSection]);

  const nativeQuarkEnabled = Boolean(config?.enabled_providers.includes("quark"));
  const p115Connected = Boolean(config?.has_p115_cookie);
  return (
    <section className="cloud-center">
      <div className="page-head cloud-center-head">
        <div>
          <p className="eyebrow">MEDIA CLOUD CONTROL</p>
          <h1>网盘工作台</h1>
          <p>从账号连接、资源验真到转存任务，所有网盘写操作都按同一条可追溯流程运行。</p>
        </div>
      </div>

      <div className="cloud-workspace-layout">
        <nav className="cloud-workspace-nav" aria-label="网盘工作台模块">
          {sections.map(({ key, label, icon: Icon }) => (
            <button key={key} type="button" className={section === key ? "active" : ""} onClick={() => setSection(key)}>
              <Icon size={19} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="cloud-workspace-content">
          {section === "overview" && (
            <div className="cloud-overview">
              <div className="cloud-overview-status">
                <span className={config?.has_quark_cookie ? "ready" : "pending"}>{config?.has_quark_cookie ? "已连接" : "待连接"}</span>
                <div><strong>夸克网盘</strong><small>{nativeQuarkEnabled ? "已接入统一检索、验真与转存流程" : "完成连接后即可用于新任务"}</small></div>
              </div>
              <div className="cloud-overview-status secondary">
                <span className={p115Connected ? "ready" : "pending"}>{p115Connected ? "已连接" : "待连接"}</span>
                <div><strong>115 网盘</strong><small>当前使用 Cookie；跨盘任务只在明确启动后才会写入目标目录。</small></div>
              </div>
              <ol className="cloud-process-map">
                <li className={config?.has_quark_cookie ? "done" : "current"}><span>01</span><strong>连接账号</strong><small>手工 Cookie</small></li>
                <li className={config?.has_quark_cookie ? "current" : ""}><span>02</span><strong>验真资源</strong><small>读取真实文件树</small></li>
                <li><span>03</span><strong>统一转存</strong><small>TMDB、命名与确认</small></li>
                <li><span>04</span><strong>STRM 与播放</strong><small>进入独立模块管理</small></li>
              </ol>
              <div className="cloud-overview-actions">
                <button type="button" className="primary" onClick={() => setSection("connections")}>连接夸克账号</button>
                <button type="button" className="ghost" onClick={() => setSection("verification")}>验证分享链接</button>
              </div>
            </div>
          )}

          {section === "connections" && <QuarkReadOnlySettings mode="connection" onChanged={() => void refresh()} />}
          {section === "verification" && <QuarkReadOnlySettings mode="verification" onChanged={() => void refresh()} />}
          {section === "transfers" && <CrossCloudTransferCenter />}
          {section === "channels" && <ChannelWorkspace />}
        </div>
      </div>
    </section>
  );
}
