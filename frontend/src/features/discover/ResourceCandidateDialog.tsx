import { WarningCircle } from "@phosphor-icons/react";
import type { ResourceCandidateOption } from "../../lib/api";
import { type CloudProvider, providerLabel } from "./mediaDetailSupport";

export function ResourceCandidateDialog({
  provider,
  options,
  onClose,
  onSelect,
}: {
  provider: CloudProvider;
  options: Array<ResourceCandidateOption & { season_number: number }>;
  onClose: () => void;
  onSelect: (option: { season_number: number; share_url: string }) => void;
}) {
  return (
    <div className="modal-backdrop candidate-backdrop" onClick={onClose}>
      <article className="candidate-choice-modal" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} title="关闭">×</button>
        <div className="candidate-choice-heading">
          <div>
            <span className="eyebrow">候选资源确认</span>
            <h2>选择要转存的{providerLabel(provider)}资源</h2>
            <p>115 分享会先验证文件；磁力按质量优先级排列，下载后核对文件并整理入库。</p>
          </div>
          <WarningCircle size={30} />
        </div>
        <div className="candidate-choice-list">
          {options.map((option, index) => (
            <button type="button" className="candidate-choice-item" key={`${option.share_url}-${option.season_number}-${index}`} onClick={() => onSelect({ season_number: option.season_number, share_url: option.share_url })}>
              <span className="candidate-choice-topline">
                <strong>{option.title || `候选资源 ${index + 1}`}</strong>
                <span>{option.season_number > 0 ? `S${option.season_number}` : "电影"}{option.score ? ` · 评分 ${option.score}` : ""}</span>
              </span>
              <span className="candidate-choice-source">{option.resource_kind === "magnet" ? "磁力云下载 · " : "网盘分享 · "}{[option.source?.startsWith("telegram:") ? option.source.replace("telegram:", "TG 频道 · ") : option.source, option.published_at].filter(Boolean).join(" · ") || "全局候选资源"}</span>
              {option.files?.length ? <span className="candidate-choice-files">{option.files.slice(0, 3).join("、")}{option.files.length > 3 ? ` 等 ${option.files.length} 个文件` : ""}</span> : <span className="candidate-choice-files">{option.resource_kind === "magnet" ? "提交到 115 云下载，完成后核验文件并整理入库" : "点击后由 MediaIndex 再次验证分享内容"}</span>}
            </button>
          ))}
        </div>
      </article>
    </div>
  );
}
