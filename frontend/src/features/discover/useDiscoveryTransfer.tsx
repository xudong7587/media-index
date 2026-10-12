import { useEffect, useRef, useState } from "react";
import { X } from "@phosphor-icons/react";
import { api, type MediaItem } from "../../lib/api";

type BatchItems = Parameters<typeof api.createTransferBatch>[1];
type Destination = { provider: string; child_name: string; path: string };

export function useDiscoveryTransfer() {
  const [choices, setChoices] = useState<Array<{ provider: string; options: Destination[] }> | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const pending = useRef<{ resolve: (paths: Record<string, string>) => void; reject: (error: Error) => void } | null>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; pending.current?.reject(new Error("已取消转存")); };
  }, []);
  useEffect(() => {
    if (!choices) return;
    function escape(event: KeyboardEvent) { if (event.key === "Escape") cancel(); }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [choices]);

  function cancel() {
    pending.current?.reject(new Error("已取消转存"));
    pending.current = null;
    setChoices(null);
  }

  async function createBatch(media: MediaItem, items: BatchItems) {
    const providers = [...new Set(items.map((item) => item.provider === "p115" ? "p115" as const : "quark" as const))];
    const destinations = await Promise.all(providers.map(async (provider) => ({
      provider, options: await api.discoveryTransferDestinations(provider),
    })));
    if (!active.current) throw new Error("已取消转存");
    setSelected({});
    const paths = await new Promise<Record<string, string>>((resolve, reject) => {
      pending.current = { resolve, reject };
      setChoices(destinations);
    });
    return api.createTransferBatch(media, items.map((item) => ({
      ...item, cloud_download_child: paths[item.provider === "p115" ? "p115" : "quark"],
    })));
  }

  const destinationDialog = choices && (
    <div className="modal-backdrop candidate-backdrop" role="presentation" onClick={cancel}>
      <article className="candidate-choice-modal" role="dialog" aria-modal="true" aria-label="选择保存路径" onClick={(event) => event.stopPropagation()}>
        <div className="candidate-choice-heading">
          <div><h3>选择保存路径</h3><p>资源先保存到所选云下载子文件夹，完成后按同名目录整理到媒体库。</p></div>
          <button className="icon" type="button" aria-label="取消目录选择" onClick={cancel}><X size={20} /></button>
        </div>
        {choices.map(({ provider, options }) => (
          <div key={provider} className="candidate-choice-list">
            <strong>{provider === "p115" ? "115" : "夸克"}</strong>
            {!options.length && <p>没有可用的云下载子文件夹，请先在云下载整理中配置目录。</p>}
            {options.map((option) => (
              <label className="candidate-choice-item" key={option.path}>
                <span><input type="radio" name={`destination-${provider}`} checked={selected[provider] === option.child_name} onChange={() => setSelected((current) => ({ ...current, [provider]: option.child_name }))} /> {option.child_name}</span>
                <span className="candidate-choice-files">{option.path}</span>
              </label>
            ))}
          </div>
        ))}
        <button className="primary" type="button" disabled={choices.some(({ provider, options }) => !options.some((option) => option.child_name === selected[provider]))} onClick={() => {
          pending.current?.resolve(selected);
          pending.current = null;
          setChoices(null);
        }}>确认路径并转存</button>
      </article>
    </div>
  );
  return { createBatch, destinationDialog };
}
