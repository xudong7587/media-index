import { type ChangeEvent, type ReactNode, useState } from "react";

import { api, ApiError } from "../../lib/api";

type Props = {
  onImported: () => Promise<void>;
  spinner: () => ReactNode;
};

export function ConfigBackupSettings({ onImported, spinner }: Props) {
  const [busy, setBusy] = useState<"export" | "import" | null>(null);
  const [message, setMessage] = useState("");

  async function exportSettings() {
    setBusy("export");
    setMessage("");
    try {
      const payload = await api.exportConfig();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "mediaindex-settings.json";
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage("已导出全部设置、智能追更和愿望单任务。文件含 Token、Cookie 等敏感凭据，请妥善保存。");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "导出失败");
    } finally {
      setBusy(null);
    }
  }

  async function importSettings(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!window.confirm("导入会覆盖当前全部设置、智能追更和愿望单任务，包含各网盘 Token、根目录和分类目录。是否继续？")) return;
    setBusy("import");
    setMessage("");
    try {
      const parsed = JSON.parse(await file.text()) as {
        format?: string;
        settings?: Record<string, string>;
        task_data?: { wishlist: Record<string, unknown>[]; tracking: Record<string, unknown>[] };
      };
      if (typeof parsed.format !== "string" || !parsed.settings || typeof parsed.settings !== "object") {
        throw new Error("配置文件格式无效");
      }
      const result = await api.importConfig({ format: parsed.format, settings: parsed.settings, task_data: parsed.task_data });
      await onImported();
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : error instanceof Error ? error.message : "导入失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="settings-section">
      <header>
        <strong>配置导入导出</strong>
        <span>导出会包含全部设置、网盘 Token、Cookie、根目录、分类目录、智能追更与愿望单任务。导入同类 JSON 后将直接覆盖这些内容。</span>
      </header>
      <div className="settings-section-body">
        <p className="settings-help config-backup-warning">导出的 JSON 包含敏感登录凭据，请勿截图、转发或提交到 Git，并妥善保存在受保护的位置。</p>
        <div className="settings-action-strip">
          <button type="button" className="primary compact-action" onClick={() => void exportSettings()} disabled={busy !== null}>
            {busy === "export" && spinner()}{busy === "export" ? "导出中" : "导出全部设置"}
          </button>
          <label className="ghost compact-action config-import-button">
            {busy === "import" && spinner()}{busy === "import" ? "导入中" : "导入并覆盖"}
            <input type="file" accept="application/json,.json" onChange={(event) => void importSettings(event)} disabled={busy !== null} />
          </label>
          {message && <div className="settings-inline-result">{message}</div>}
        </div>
      </div>
    </section>
  );
}
