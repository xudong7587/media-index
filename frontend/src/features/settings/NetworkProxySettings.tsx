import type { ConfigStatus } from "../../lib/api";
import { SettingsInput } from "./SettingsFormParts";
import { SettingsSection } from "./SettingsUi";

export function NetworkProxySettings({ config, value, saving, testing, result, onChange, onTest }: {
  config: ConfigStatus;
  value: string;
  saving: boolean;
  testing: boolean;
  result: { ok: boolean; message: string } | null;
  onChange: (key: string, value: string) => void;
  onTest: () => void;
}) {
  return (
    <SettingsSection title="网络代理" body="让 MediaIndex 容器通过指定代理访问 TMDB 等外部服务；这里不是 Emby 反向代理或 STRM 播放地址。">
      <SettingsInput label="代理地址" name="proxy_url" saved={config.has_proxy} value={value} onChange={onChange} placeholder={config.proxy_url || "http://192.168.1.2:7890"} action={<button type="button" className="primary compact-action" onClick={onTest} disabled={testing || saving}>{testing && <span className="spinner" aria-hidden="true" />}{testing ? "测试中" : "测试代理"}</button>} result={result} />
      <div className="notice page-notice proxy-settings-guide">
        <strong>局域网代理填写方式</strong>
        <span>填写代理设备在 NAS 局域网中的可达地址，例如 <code>http://192.168.31.81:7890</code>。不要填写手机或电脑自己的 <code>127.0.0.1</code>，因为容器中的本机地址指向容器自身。</span>
        <span>代理软件需要开启“允许局域网连接”，NAS 防火墙需放行对应端口。支持 HTTP/HTTPS 代理；需要认证时可填写 <code>http://用户名:密码@内网地址:端口</code>。</span>
        <span>测试会从 MediaIndex 容器实际访问 TMDB。PanSou、QAS、OpenList 和网盘等本机、Docker 服务名或局域网地址会保持直连，避免被外部代理阻断。</span>
      </div>
    </SettingsSection>
  );
}
