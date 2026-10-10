import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Download, LoaderCircle, RefreshCw, ShieldAlert, Wrench } from "lucide-react";
import { getUxMetrics, onUxMetricsChange, resetUxMetrics } from "../lib/analytics";
import { checkServerHealth, logoutAccount } from "../lib/authApi";
import type { AuthState, Diagnostics, ServerConnectionStatus, UpdateInfo } from "../types";

export function SettingsPage({
  auth,
  diagnostics,
  diagnosticsReady,
  currentVersion,
  updateInfo,
  updateChecking,
  updateError,
  onCheckUpdates,
  onAuthChange,
  onLogout,
}: {
  auth: AuthState;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  currentVersion: string;
  updateInfo: UpdateInfo | null;
  updateChecking: boolean;
  updateError: string;
  onCheckUpdates: () => void;
  onAuthChange: (a: AuthState) => void;
  onLogout: () => void;
}) {
  const [customServerUrl, setCustomServerUrl] = useState("");
  const [metrics, setMetrics] = useState(getUxMetrics);
  const [connection, setConnection] = useState<{ status: ServerConnectionStatus; message: string; checkedAt: string }>({
    status: "checking",
    message: "正在检测服务器…",
    checkedAt: "",
  });

  const checkConnection = useCallback(async () => {
    setConnection({ status: "checking", message: "正在检测服务器…", checkedAt: "" });
    try {
      const health = await checkServerHealth(auth.serverUrl);
      if (!health.ok) throw new Error(`服务器状态：${health.status}`);
      setConnection({ status: "connected", message: "会员服务器响应正常", checkedAt: health.time });
    } catch (error) {
      setConnection({
        status: "failed",
        message: error instanceof Error ? error.message : "无法连接会员服务器",
        checkedAt: "",
      });
    }
  }, [auth.serverUrl]);

  const applyServerUrl = () => {
    const nextUrl = customServerUrl.trim().replace(/\/+$/, "");
    if (!nextUrl) return;
    if (nextUrl !== "https://videomix.7cloudvps.com") {
      setConnection({ status: "failed", message: "正式版仅支持官方会员服务器 https://videomix.7cloudvps.com", checkedAt: "" });
      return;
    }
    if (auth.token) void logoutAccount(auth.serverUrl, auth.token).catch(() => undefined);
    onAuthChange({
      ...auth,
      serverUrl: nextUrl,
      username: "",
      token: "",
      active: false,
      plan: "none",
      planLabel: "未开通",
      expiresAt: "",
      sessionExpiresAt: "",
      deviceName: "",
      deviceBoundAt: "",
      deviceRebindCooldownUntil: "",
      deviceRebindRemainingSeconds: 0,
    });
    setCustomServerUrl("");
  };

  useEffect(() => onUxMetricsChange(() => setMetrics(getUxMetrics())), []);
  useEffect(() => { void checkConnection(); }, [checkConnection]);

  const startFailureRate = metrics.startAttempts > 0 ? Math.round(metrics.startFailures / metrics.startAttempts * 100) : 0;
  const finishedRetries = metrics.retrySuccesses + metrics.retryFailures;
  const retrySuccessRate = finishedRetries > 0 ? Math.round(metrics.retrySuccesses / finishedRetries * 100) : 0;

  return (
    <div>
      <h1 className="page-title">设置</h1>
      <p className="page-subtitle">服务配置与组件状态</p>

      <div className="dashboard-main">
        <div className="panel update-panel">
          <div className="panel-header">
            <span className="panel-title">版本与更新</span>
            <button className="btn btn-secondary btn-sm" onClick={onCheckUpdates} disabled={updateChecking}>
              <RefreshCw size={13} className={updateChecking ? "spin" : undefined} />
              {updateChecking ? "正在检查" : "检查更新"}
            </button>
          </div>
          <div className={`update-card ${updateInfo?.updateAvailable ? "available" : "current"}`} aria-live="polite">
            <div className="update-version-row">
              <div>
                <small>当前版本</small>
                <strong>v{currentVersion}</strong>
              </div>
              {updateInfo?.updateAvailable ? (
                <span className={`status-chip ${updateInfo.required ? "failed" : "checking"}`}>
                  {updateInfo.required && <ShieldAlert size={12} />}
                  {updateInfo.required ? "必须更新" : `可更新至 v${updateInfo.latestVersion}`}
                </span>
              ) : !updateChecking && !updateError ? <span className="status-chip connected"><CheckCircle2 size={12} />已是最新版</span> : null}
            </div>
            {updateError && <div className="component-warning"><AlertCircle size={15} />{updateError}</div>}
            {updateInfo?.updateAvailable && (
              <>
                <div className="update-notes">
                  <strong>{updateInfo.title || `Video Mix Pro ${updateInfo.latestVersion}`}</strong>
                  <p>{updateInfo.notes || "此版本包含功能更新与稳定性改进。"}</p>
                  {updateInfo.sha256 && <code title={updateInfo.sha256}>SHA-256：{updateInfo.sha256}</code>}
                </div>
                <button className="btn btn-primary btn-sm update-download" disabled={!updateInfo.downloadUrl} onClick={() => void openDownload(updateInfo.downloadUrl)}>
                  <Download size={14} />
                  {updateInfo.downloadUrl ? "从 GitHub 下载" : "下载链接待发布"}
                </button>
              </>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">服务</span>
            <button className="btn btn-secondary btn-sm" onClick={() => void checkConnection()} disabled={connection.status === "checking"}>
              <RefreshCw size={13} className={connection.status === "checking" ? "spin" : undefined} />
              重新检测
            </button>
          </div>
          <div className="service-status-card" aria-live="polite">
            <div className={`service-status-icon ${connection.status}`}>
              {connection.status === "checking" && <LoaderCircle size={18} className="spin" />}
              {connection.status === "connected" && <CheckCircle2 size={18} />}
              {connection.status === "failed" && <AlertCircle size={18} />}
            </div>
            <div className="service-status-copy">
              <strong>{connection.status === "connected" ? "服务器可用" : connection.status === "failed" ? "连接失败" : "检测中"}</strong>
              <span>{connection.message}</span>
              <code title={auth.serverUrl}>{auth.serverUrl}</code>
              {connection.checkedAt && <small>服务器时间：{formatDateTime(connection.checkedAt)}</small>}
            </div>
          </div>
          <div className="input-field" style={{ marginTop: 12 }}>
            <label>恢复官方会员服务器</label>
            <div className="input-with-btn">
              <input
                type="text"
                value={customServerUrl}
                onChange={(e) => setCustomServerUrl(e.target.value)}
                placeholder="https://videomix.7cloudvps.com"
              />
              <button className="btn btn-secondary btn-sm" onClick={applyServerUrl} disabled={!customServerUrl.trim()}>
                保存
              </button>
            </div>
            <span className="input-hint">正式版仅连接官方会员服务器；保存会注销当前账号，需要重新登录。</span>
          </div>
          <button className="btn btn-danger btn-sm" onClick={onLogout}>
            退出登录并注销会话
          </button>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">组件</span>
          </div>
          <ToolStatus label="FFmpeg" ready={diagnosticsReady} available={diagnostics.hasFfmpeg} path={diagnostics.ffmpegPath} fileName="ffmpeg.exe" />
          <ToolStatus label="FFprobe" ready={diagnosticsReady} available={diagnostics.hasFfprobe} path={diagnostics.ffprobePath} fileName="ffprobe.exe" />
          {diagnosticsReady && (!diagnostics.hasFfmpeg || !diagnostics.hasFfprobe) && (
            <div className="component-warning"><AlertCircle size={15} />组件缺失会导致扫描或生成失败，请将对应程序放入软件目录。</div>
          )}
        </div>

        <div className="panel ux-metrics-panel">
          <div className="panel-header">
            <span className="panel-title">体验指标</span>
            <button className="btn btn-ghost btn-sm" onClick={() => { resetUxMetrics(); setMetrics(getUxMetrics()); }}>重置</button>
          </div>
          <p className="input-hint">指标仅保存在本机，用于判断交互优化是否有效。</p>
          <div className="ux-metrics-grid">
            <Metric label="首次生成耗时" value={metrics.firstTaskCompletionMs ? formatDuration(metrics.firstTaskCompletionMs) : "等待首次完成"} />
            <Metric label="开始失败率" value={`${startFailureRate}%`} detail={`${metrics.startFailures}/${metrics.startAttempts} 次`} />
            <Metric label="提交后返回修改" value={`${metrics.postSubmitEditSessions} 次`} />
            <Metric label="失败重试成功率" value={finishedRetries ? `${retrySuccessRate}%` : "暂无数据"} detail={finishedRetries ? `${metrics.retrySuccesses}/${finishedRetries} 次` : undefined} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ToolStatus({ label, ready, available, path, fileName }: { label: string; ready: boolean; available: boolean; path: string; fileName: string }) {
  const state = !ready ? "checking" : available ? "connected" : "failed";
  return (
    <div className="tool-status-row">
      <div className="tool-status-name"><Wrench size={15} /><span>{label}</span></div>
      <div className="tool-status-detail">
        <span className={`status-chip ${state}`}>
          {!ready ? <LoaderCircle size={13} className="spin" /> : available ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
          {!ready ? "检测中" : available ? "可用" : "未找到"}
        </span>
        <small title={path}>{ready ? formatToolPath(path, fileName) : "正在读取组件信息…"}</small>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="ux-metric"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remain = seconds % 60;
  return remain ? `${minutes} 分 ${remain} 秒` : `${minutes} 分钟`;
}

function formatToolPath(path: string, fileName: string): string {
  if (!path) return "待放入";
  const normalized = path.replace(/\\/g, "/");
  if (normalized.toLowerCase().endsWith(`/bin/${fileName.toLowerCase()}`)) {
    return `已内置 / bin\\${fileName}`;
  }
  return path.split(/[\\/]/).pop() || "已找到";
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
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
