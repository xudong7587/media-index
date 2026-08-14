import { FloppyDisk } from "@phosphor-icons/react";

export function SettingsSaveFab({ formId }: { formId: string }) {
  return (
    <button
      type="submit"
      className="settings-save-fab"
      form={formId}
      title="保存当前设置"
      aria-label="保存当前设置"
    >
      <FloppyDisk size={24} weight="bold" />
      <span className="settings-save-fab-label">保存设置</span>
    </button>
  );
}
