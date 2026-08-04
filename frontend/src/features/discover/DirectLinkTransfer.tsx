import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowRight, CloudArrowDown, Link, SpinnerGap, X } from "@phosphor-icons/react";
import { api, ApiError } from "../../lib/api";

type DirectLinkOption = {
  provider: "qas" | "p115";
  path: string;
  label: string;
  category?: string;
};

type DirectLinkPreview = {
  link: string;
  provider: "qas" | "p115";
  root_path: string;
  year?: string;
  options: DirectLinkOption[];
};

type Props = {
  onMessage: (message: string) => void;
  category?: string;
};

const providerLabels = { qas: "夸克", p115: "115" } as const;

export function DirectLinkTransfer({ onMessage, category = "movie" }: Props) {
  const [link, setLink] = useState("");
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [options, setOptions] = useState<DirectLinkOption[]>([]);
  const [provider, setProvider] = useState<"qas" | "p115">("qas");
  const [pendingLink, setPendingLink] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = link.trim();
    if (!value || busy) return;
    setBusy(true);
    onMessage("");
    try {
      const preview: DirectLinkPreview = await api.directLinkOptions(value, title, year, category);
      setProvider(preview.provider);
      setPendingLink(preview.link);
      if (preview.year && !year) setYear(preview.year);
      if (preview.options.length > 1) {
        setOptions(preview.options);
        return;
      }
      await transfer(
        preview.link,
        preview.options[0]?.path || preview.root_path,
        preview.provider,
        preview.options[0]?.category || category,
        preview.year || year,
      );
    } catch (error) {
      onMessage(error instanceof ApiError || error instanceof Error ? error.message : "链接解析失败");
    } finally {
      if (options.length <= 1) setBusy(false);
    }
  }

  async function transfer(value: string, savePath: string, selectedProvider = provider, selectedCategory = category, selectedYear = year) {
    try {
      const result = await api.directLinkTransfer(value, savePath, title, selectedYear, selectedCategory);
      setLink("");
      setTitle("");
      setYear("");
      setOptions([]);
      setPendingLink("");
      onMessage(`${providerLabels[selectedProvider]}：${result.message}`);
    } catch (error) {
      onMessage(error instanceof ApiError || error instanceof Error ? error.message : "链接转存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="direct-link-bar" onSubmit={submit}>
        <div className="direct-link-label">
          <Link size={18} />
          <span>链接转存</span>
        </div>
        <input
          aria-label="资源名"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="资源名（可选）"
        />
        <input
          aria-label="资源年份"
          value={year}
          onChange={(event) => setYear(event.target.value.replace(/[^0-9]/g, "").slice(0, 4))}
          placeholder="年份（可选）"
          inputMode="numeric"
        />
        <input
          aria-label="粘贴下载链接"
          value={link}
          onChange={(event) => setLink(event.target.value)}
          placeholder="粘贴夸克、115 或磁力链接"
          inputMode="url"
        />
        <button className="primary direct-link-submit" type="submit" disabled={busy || !link.trim()}>
          {busy ? <SpinnerGap className="spin" size={17} /> : <CloudArrowDown size={17} />}
          {busy ? "解析中" : "转存"}
        </button>
      </form>
      {options.length > 1 && (
        <div className="direct-link-picker" role="dialog" aria-label="选择媒体库类型">
          <div className="direct-link-picker-head">
            <div>
              <strong>选择媒体库类型</strong>
          <span>{providerLabels[provider]}：请选择媒体库分类，系统会自动生成对应目录</span>
            </div>
            <button className="icon" type="button" onClick={() => { setOptions([]); setBusy(false); }} aria-label="关闭目录选择">
              <X size={18} />
            </button>
          </div>
          <div className="direct-link-options">
            {options.map((option) => (
              <button
                className="direct-link-option"
                type="button"
                key={`${option.provider}:${option.path}`}
                onClick={() => void transfer(pendingLink, option.path, option.provider, option.category || category)}
                disabled={busy}
              >
                <span>{option.label}</span>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
