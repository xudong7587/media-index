import React, { useState } from "react";
import { Eye, EyeSlash, Question } from "@phosphor-icons/react";
import { api } from "../../lib/api";

export function SettingsToggle({
  label,
  help,
  value,
  onChange,
  trueLabel = "开",
  falseLabel = "关",
  disabled = false,
  busy = false,
}: {
  label: string;
  help?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  trueLabel?: string;
  falseLabel?: string;
  disabled?: boolean;
  busy?: boolean;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  return (
    <div className="settings-field">
      <span className="settings-label">
        {label}
        {help && (
          <span className="inline-help-wrap">
            <button type="button" className="inline-help" aria-label={`${label}说明`} aria-expanded={helpOpen} onClick={() => setHelpOpen((current) => !current)} onBlur={() => window.setTimeout(() => setHelpOpen(false), 120)}>
              <Question size={15} weight="bold" />
            </button>
            <span className={`inline-help-popover ${helpOpen ? "open" : ""}`} role="tooltip">{help}</span>
          </span>
        )}
      </span>
      <div className="toggle-group" role="group" aria-label={label}>
        <button type="button" className={value ? "active" : ""} onClick={() => onChange(true)} disabled={disabled}>
          {busy && value && <span className="spinner" aria-hidden="true" />}
          {trueLabel}
        </button>
        <button type="button" className={!value ? "active" : ""} onClick={() => onChange(false)} disabled={disabled}>
          {busy && !value && <span className="spinner" aria-hidden="true" />}
          {falseLabel}
        </button>
      </div>
    </div>
  );
}

export function SettingsInput({ label, name, value, saved, help, helpTooltip, secret, placeholder, showSavedValue, onChange, onReveal, action, result }: {
  label: string;
  name: string;
  value: string;
  saved: boolean;
  help?: string;
  helpTooltip?: string;
  secret?: boolean;
  placeholder?: string;
  showSavedValue?: boolean;
  onChange: (key: string, value: string) => void;
  onReveal?: (value: string) => void;
  action?: React.ReactNode;
  result?: { ok: boolean; message: string } | null;
}) {
  const [secretVisible, setSecretVisible] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState("");
  const savedPlaceholder = savedInputPlaceholder(name, placeholder, showSavedValue ?? !secret, Boolean(secret));
  async function toggleSecretVisibility() {
    if (secretVisible) {
      setSecretVisible(false);
      setRevealedSecret("");
      return;
    }
    if (!value && saved) {
      try {
        const result = await api.configSecret(name);
        setRevealedSecret(result.value);
        onReveal?.(result.value);
      } catch {
        setRevealedSecret("");
      }
    }
    setSecretVisible(true);
  }
  return (
    <div className="settings-field">
      <span className="settings-label">{label}{helpTooltip && <InlineHelp label={label} text={helpTooltip} />}{help && <small className="settings-field-help">{help}</small>}</span>
      <div className="settings-input-content">
        <div className="settings-input-action">
          <div className={secret ? "settings-secret-input" : "settings-plain-input"}>
            <input aria-label={label} type={secret && !secretVisible ? "password" : "text"} value={value || revealedSecret} placeholder={saved ? savedPlaceholder : placeholder || "未配置"} onChange={(event) => { setRevealedSecret(""); onChange(name, event.target.value); }} />
            {secret && <button type="button" className="settings-secret-visibility" aria-label={secretVisible ? `隐藏${label}` : `显示${label}`} title={secretVisible ? "隐藏" : "显示"} onClick={() => void toggleSecretVisibility()}>{secretVisible ? <EyeSlash size={19} /> : <Eye size={19} />}</button>}
          </div>
          {action}
        </div>
        {result && <div className={`settings-inline-result ${result.ok ? "success" : "error"}`}>{result.message}</div>}
      </div>
    </div>
  );
}

export function InlineHelp({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-help-wrap">
      <button type="button" className="inline-help" aria-label={`${label}说明`} aria-expanded={open} onClick={() => setOpen((current) => !current)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}>
        <Question size={15} weight="bold" />
      </button>
      <span className={`inline-help-popover ${open ? "open" : ""}`} role="tooltip">{text}</span>
    </span>
  );
}

export function savedInputPlaceholder(name: string, placeholder = "", showSavedValue = false, secret = false) {
  if (!showSavedValue || !placeholder) return "已保存，如需修改请重新填写";
  const shouldMask = secret || /(token|cookie|secret|api_key|password)/i.test(name);
  if (shouldMask) return "已保存，如需修改请重新填写";
  return `${placeholder}，如需修改请重新填写`;
}
