import { Download, RefreshCw, ShieldAlert, X } from "lucide-react";
import type { UpdateInfo } from "../types";

export function ForcedUpdateDialog({
  currentVersion,
  updateInfo,
  checking,
  error,
  onRetry,
}: {
  currentVersion: string;
  updateInfo: UpdateInfo;
  checking: boolean;
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="forced-update-backdrop" role="presentation">
      <section className="forced-update-dialog" role="alertdialog" aria-modal="true" aria-labelledby="forcedUpdateTitle" aria-describedby="forcedUpdateDescription">
        <div className="forced-update-icon"><ShieldAlert size={28} /></div>
        <div className="forced-update-heading">
          <span>REQUIRED UPDATE</span>
          <h2 id="forcedUpdateTitle">必须更新后才能继续使用</h2>
          <p id="forcedUpdateDescription">当前版本已低于后台设置的最低支持版本，为保证账号与任务兼容，请先安装最新版。</p>
        </div>

        <div className="forced-update-versions">
          <div><small>当前版本</small><strong>v{currentVersion}</strong></div>
          <div><small>最低支持</small><strong>v{updateInfo.minimumVersion}</strong></div>
          <div><small>可更新至</small><strong>v{updateInfo.latestVersion}</strong></div>
        </div>

        <div className="forced-update-notes">
          <strong>{updateInfo.title || `Video Mix Pro ${updateInfo.latestVersion}`}</strong>
          <p>{updateInfo.notes || "此版本包含必要的兼容性与稳定性更新。"}</p>
        </div>

        {error && <div className="component-warning">{error}</div>}
        {!updateInfo.downloadUrl && <div className="component-warning">管理员尚未配置下载链接，请稍后重试或联系管理员。</div>}

        <div className="forced-update-actions">
          <button className="btn btn-primary btn-lg" disabled={!updateInfo.downloadUrl} onClick={() => void openDownload(updateInfo.downloadUrl)}>
            <Download size={16} />下载最新版
          </button>
          <button className="btn btn-secondary btn-lg" onClick={onRetry} disabled={checking}>
            <RefreshCw size={16} className={checking ? "spin" : undefined} />{checking ? "正在检查" : "重新检查"}
          </button>
          <button className="btn btn-ghost btn-lg forced-update-exit" onClick={() => void exitApplication()}>
            <X size={16} />退出软件
          </button>
        </div>
      </section>
    </div>
  );
}

async function openDownload(url: string): Promise<void> {
  if (!url) return;
  if ("__TAURI_INTERNALS__" in window) {
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

async function exitApplication(): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().close();
    return;
  }
  window.close();
}
