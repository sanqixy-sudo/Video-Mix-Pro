import { cancelRenderTask, clearFinishedTasks, clearPendingTasks, getRenderStatus, openDirectory, removeQueuedTask, retryQueueTask } from "../lib/tauri";
import { recordRetryAttempt } from "../lib/analytics";
import type { QueueTaskStatus, RenderTaskStatus } from "../types";

export function TasksPage({
  status,
  onStatusChange,
}: {
  status: RenderTaskStatus;
  onStatusChange: (status: RenderTaskStatus) => void;
}) {
  const pending = status.queue.filter((item) => item.status === "waiting");
  const finished = status.queue
    .filter((item) => ["completed", "completed_with_errors", "cancelled"].includes(item.status))
    .slice()
    .reverse();
  const current = status.queue.find((item) => item.id === status.currentTaskId);

  const handleRefresh = async () => onStatusChange(await getRenderStatus());
  const handleCancel = async () => onStatusChange(await cancelRenderTask());
  const handleRemove = async (taskId: string) => onStatusChange(await removeQueuedTask(taskId));
  const handleClearPending = async () => onStatusChange(await clearPendingTasks());
  const handleClearFinished = async () => onStatusChange(await clearFinishedTasks());
  const handleRetry = async (taskId: string) => {
    recordRetryAttempt();
    onStatusChange(await retryQueueTask(taskId));
  };

  const handleExport = () => {
    const blob = new Blob([status.logs.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "video-mix-task-log.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <h1 className="page-title">任务中心</h1>
      <p className="page-subtitle">任务会按提交顺序自动执行，可以继续配置并添加新任务</p>

      <div className="panel">
        <div className="task-header">
          <span className="panel-title">当前任务{status.taskKind ? `：${status.taskKind}` : ""}</span>
          <span className={`queue-state ${status.running ? "running" : ""}`}>{status.running ? status.status : "当前空闲"}</span>
        </div>

        {current || status.running ? (
          <>
            {current && <div className="queue-current-name">{current.name}</div>}
            {status.outputFolder && <p className="page-subtitle queue-output-path">输出目录：{status.outputFolder}</p>}
            <div className="task-progress">
              <div className="progress-bar-track">
                <div className="progress-bar-fill" style={{ width: `${status.progress}%` }} />
              </div>
              <span className="queue-progress-text">{status.progress}%</span>
            </div>
            <div className="stats-bar queue-stats">
              <div className="stat-item"><strong>{status.completed}</strong><span>已完成</span></div>
              <div className="stat-item"><strong>{status.failed}</strong><span>失败</span></div>
              <div className="stat-item"><strong>{status.total}</strong><span>总计</span></div>
            </div>
          </>
        ) : (
          <div className="queue-empty">当前没有正在运行的任务，可以从左侧选择工具继续添加。</div>
        )}

        <div className="dashboard-actions queue-actions">
          <button className="btn btn-secondary" onClick={handleRefresh}>刷新状态</button>
          {status.outputFolder && <button className="btn btn-secondary" onClick={() => openDirectory(status.outputFolder)}>打开输出目录</button>}
          <button className="btn btn-danger" onClick={handleCancel} disabled={!status.running}>取消当前任务</button>
        </div>
      </div>

      <div className="panel queue-panel">
        <div className="panel-header">
          <span className="panel-title">等待队列 <span className="queue-count">{pending.length}</span></span>
          <button className="btn btn-ghost btn-sm" onClick={handleClearPending} disabled={pending.length === 0}>清空等待任务</button>
        </div>
        {pending.length === 0 ? (
          <div className="queue-empty compact">暂无等待任务</div>
        ) : (
          <div className="queue-list">
            {pending.map((item, index) => (
              <QueueItem key={item.id} item={item} position={index + 1} onRemove={() => handleRemove(item.id)} />
            ))}
          </div>
        )}
      </div>

      {finished.length > 0 && (
        <div className="panel queue-panel">
          <div className="panel-header">
            <span className="panel-title">最近完成</span>
            <button className="btn btn-ghost btn-sm" onClick={handleClearFinished}>清空记录</button>
          </div>
          <div className="queue-list">
            {finished.map((item) => <QueueItem key={item.id} item={item} onOpen={() => openDirectory(item.outputFolder)} onRetry={item.failed > 0 || item.status === "cancelled" ? () => handleRetry(item.id) : undefined} />)}
          </div>
        </div>
      )}

      <div className="panel queue-panel">
        <div className="panel-header">
          <span className="panel-title">当前任务日志</span>
          <button className="btn btn-ghost btn-sm" onClick={handleExport}>导出</button>
        </div>
        <div className="task-log">{status.logs.join("\n")}</div>
      </div>
    </div>
  );
}

function QueueItem({ item, position, onRemove, onOpen, onRetry }: { item: QueueTaskStatus; position?: number; onRemove?: () => void; onOpen?: () => void; onRetry?: () => void }) {
  return (
    <div className="queue-item">
      <div className="queue-item-main">
        <div className="queue-item-title">
          {position && <span className="queue-position">{position}</span>}
          <strong>{item.taskKind}</strong>
          <span>{item.name}</span>
        </div>
        <div className="queue-item-meta">
          <span>{item.total} 条</span>
          <span>{formatTime(item.createdAt)}</span>
          <span className={`queue-state ${item.status}`}>{statusLabel(item.status)}</span>
        </div>
        <div className="queue-item-path" title={item.outputFolder}>{item.outputFolder}</div>
      </div>
      <div className="queue-item-actions">
        {onOpen && <button className="btn btn-ghost btn-sm" onClick={onOpen}>打开目录</button>}
        {onRetry && <button className="btn btn-secondary btn-sm" onClick={onRetry}>重试失败</button>}
        {onRemove && <button className="btn btn-ghost btn-sm" onClick={onRemove}>移除</button>}
      </div>
    </div>
  );
}

function statusLabel(status: QueueTaskStatus["status"]): string {
  switch (status) {
    case "waiting": return "等待中";
    case "running": return "运行中";
    case "cancelling": return "正在取消";
    case "completed": return "已完成";
    case "completed_with_errors": return "完成但有失败";
    case "cancelled": return "已取消";
  }
}

function formatTime(timestamp: number): string {
  if (!timestamp) return "";
  return new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
