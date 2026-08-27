import { CheckCircle, Checks, CircleNotch, Info, TerminalWindow } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import "./interaction-command-settings.css";

type InteractionProvider = "quark" | "p115";
type InteractionShortcut = "strm_full" | "strm_incremental" | "strm_directory" | "tracking" | "wishlist" | "status" | "review";

const shortcutGroups = [
  ["STRM", [["strm_full", "全量扫描"], ["strm_incremental", "增量扫描"], ["strm_directory", "指定目录扫描"]]],
  ["订阅管理", [["tracking", "智能追更"], ["wishlist", "愿望单"]]],
  ["服务器信息", [["status", "服务器状态"], ["review", "待确认任务"]]],
] as const;

const commands = [
  ["资源名", "搜索影视，确认条目后回复数字选择云下载子目录"],
  ["本地 资源名", "搜索影视并将确认后的资源保存到本地"],
  ["分享链接", "夸克或 115 分享链接选择云下载子目录；编号后可附名称和年份作为整理提示"],
  ["磁力链接", "提交 115 云下载并选择云下载子目录"],
  ["/review", "查看待确认任务，并通过编号选择候选资源"],
  ["/status", "查看追更、愿望单、待确认和未读通知数量"],
  ["/tracking", "查看最近的智能追更任务"],
  ["/strm_full", "对所有已启用且已选择子目录的网盘执行全量扫描"],
  ["/strm_incremental", "对所有已启用且已选择子目录的网盘执行增量扫描"],
  ["/strm_directory", "列出 STRM 来源根目录的一级子目录，回复数字执行指定扫描"],
  ["/download", "提示输入资源名称或下载链接"],
  ["/wishlist", "查看最近的愿望单任务"],
  ["/notifications", "查看最近通知"],
  ["/cancel", "取消当前等待中的编号选择"],
  ["/help", "查看交互渠道的内置指令帮助"],
] as const;

export function InteractionCommandSettings({
  providers,
  shortcuts,
  syncing,
  onProviderChange,
  onShortcutChange,
  onSaveAndSync,
}: {
  providers: InteractionProvider[];
  shortcuts: string[];
  syncing: boolean;
  onProviderChange: (provider: InteractionProvider, enabled: boolean) => void;
  onShortcutChange: (shortcut: InteractionShortcut, enabled: boolean) => void;
  onSaveAndSync: () => void;
}) {
  return (
    <div className="interaction-command-settings">
      <InteractionSettingsSection className="interaction-command-section" title="交互指令" body="企业微信和 Telegram 共用以下设置，不需要分别配置。">
        <div className="interaction-command-summary">
          <strong>共用交互规则</strong>
          <span>参与网盘、云下载子目录选择、名称与年份提示和内置指令会同时作用于企业微信与 Telegram。</span>
        </div>
        <div className="interaction-provider-settings">
          <div className="interaction-provider-heading">
            <strong>参与交互的网盘</strong>
            <span>资源名与分享链接会列出已勾选网盘的云下载子目录；智能追更沿用用户确认的网盘。</span>
          </div>
          <div className="interaction-provider-grid">
            {(["quark", "p115"] as InteractionProvider[]).map((provider) => (
              <InteractionToggle
                key={provider}
                label={provider === "quark" ? "夸克" : "115"}
                value={providers.includes(provider)}
                onChange={(value) => onProviderChange(provider, value)}
                trueLabel="参与"
                falseLabel="不参与"
              />
            ))}
          </div>
        </div>
        <div className="interaction-shortcut-settings">
          <div className="interaction-provider-heading">
            <strong>快捷菜单</strong>
            <span>按 STRM、订阅管理和服务器信息三组同步企业微信底部菜单与 Telegram 命令。指定目录扫描会在会话中列出来源根目录的一级子目录。</span>
          </div>
          <div className="interaction-shortcut-groups">
            {shortcutGroups.map(([group, groupShortcuts]) => (
              <fieldset className="interaction-shortcut-group" key={group}>
                <legend>{group}</legend>
                <div className="interaction-shortcut-grid">
                  {groupShortcuts.map(([value, label]) => (
                    <label key={value}>
                      <input type="checkbox" checked={shortcuts.includes(value)} onChange={(event) => onShortcutChange(value, event.target.checked)} />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
          <div className="settings-action-strip">
            <button type="button" className="primary compact-action" disabled={syncing} onClick={onSaveAndSync}>
              {syncing ? <CircleNotch className="spin" size={17} /> : <Checks size={17} />}
              {syncing ? "同步中" : "保存并同步快捷菜单"}
            </button>
          </div>
        </div>
        <CommandReference />
      </InteractionSettingsSection>
      <section className="interaction-overview" aria-labelledby="interaction-overview-title">
        <div>
          <strong id="interaction-overview-title">交互指令支持企业微信和 Telegram</strong>
          <p>两端使用同一套资源搜索、链接转存、编号选择和状态查询逻辑；企业微信使用应用底部菜单，Telegram 使用消息按钮和命令菜单。</p>
        </div>
        <div className="interaction-capabilities">
          <span><CheckCircle size={17} />企业微信自建应用：支持按钮交互</span>
          <span><CheckCircle size={17} />Telegram：支持按钮交互</span>
          <span><Info size={17} />群机器人：仅发送通知</span>
        </div>
      </section>
    </div>
  );
}

function InteractionSettingsSection({
  title,
  body,
  children,
  className = "",
}: {
  title: string;
  body: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`settings-section ${className}`.trim()}>
      <header>
        <strong>{title}</strong>
        <span>{body}</span>
      </header>
      <div className="settings-section-body">{children}</div>
    </section>
  );
}

function InteractionToggle({
  label,
  value,
  onChange,
  trueLabel,
  falseLabel,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
  trueLabel: string;
  falseLabel: string;
}) {
  return (
    <div className="settings-field">
      <span className="settings-label">{label}</span>
      <div className="toggle-group" role="group" aria-label={label}>
        <button type="button" className={value ? "active" : ""} onClick={() => onChange(true)}>{trueLabel}</button>
        <button type="button" className={!value ? "active" : ""} onClick={() => onChange(false)}>{falseLabel}</button>
      </div>
    </div>
  );
}

function CommandReference() {
  return (
    <section className="command-reference" aria-labelledby="command-reference-title">
      <div className="command-reference-heading">
        <TerminalWindow size={23} aria-hidden />
        <div>
          <strong id="command-reference-title">内置指令速查</strong>
          <span>在企业微信自建应用或 Telegram 会话中直接发送</span>
        </div>
      </div>
      <div className="command-reference-grid">
        {commands.map(([command, description]) => (
          <div className="command-reference-item" key={command}>
            <code>{command}</code>
            <span>{description}</span>
          </div>
        ))}
      </div>
      <p>编号选择有效期为 30 分钟。回复数字确认当前选项，发送“取消”或 <code>/cancel</code> 终止选择。</p>
    </section>
  );
}
