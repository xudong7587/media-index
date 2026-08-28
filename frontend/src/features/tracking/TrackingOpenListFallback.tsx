import { Check, CircleNotch } from "@phosphor-icons/react";
import "./tracking-surfaces.css";

type TrackingOpenListFallbackProps = {
  enabled: boolean;
  available: boolean;
  disabledReason: string;
  saving: boolean;
  onToggle: () => void;
};

export function TrackingOpenListFallback({
  enabled,
  available,
  disabledReason,
  saving,
  onToggle,
}: TrackingOpenListFallbackProps) {
  const canToggle = enabled || available;
  const switchTitle = canToggle
    ? enabled ? "关闭本季夸克到 115 自动补齐" : "开启本季夸克到 115 自动补齐"
    : disabledReason;

  return (
    <section className="tracking-openlist-fallback" aria-label="OpenList 自动补齐">
      <div className="tracking-openlist-fallback-copy">
        <div className="tracking-openlist-fallback-title">
          <strong>OpenList 自动补齐</strong>
          <span className="tracking-openlist-direction" aria-label="夸克到 115">
            夸克 <span className="tracking-sync-glyph" aria-hidden="true">⇄</span> 115
          </span>
        </div>
        <p>仅在本季夸克原生转存成功、且 115 明确未找到资源时触发。</p>
      </div>
      <div className="tracking-openlist-fallback-actions">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          className={`tracking-openlist-fallback-switch ${enabled ? "active" : ""}`}
          disabled={saving || !canToggle}
          title={switchTitle}
          onClick={onToggle}
        >
          {saving
            ? <CircleNotch className="tracking-openlist-fallback-spinner" size={15} />
            : <span className="tracking-openlist-fallback-switch-mark">{enabled && <Check size={11} weight="bold" />}</span>}
          {saving ? "保存中" : enabled ? "已开启" : "开启"}
        </button>
        <span className="tracking-openlist-reverse-disabled" title="暂不支持从 115 复制到夸克">
          <button type="button" disabled aria-label="115 到夸克暂不支持">115 → 夸克</button>
        </span>
      </div>
      {!available && <p className="tracking-openlist-fallback-hint">{disabledReason}</p>}
    </section>
  );
}
