import type { QueueTaskStatus } from "../types";

const METRICS_KEY = "video_mix_ux_metrics_v1";
const METRICS_EVENT = "video-mix-metrics-updated";

export interface UxMetrics {
  firstOpenedAt: number;
  firstTaskSubmittedAt: number;
  firstTaskCompletedAt: number;
  firstTaskCompletionMs: number;
  startAttempts: number;
  startFailures: number;
  postSubmitEditSessions: number;
  retryAttempts: number;
  retrySuccesses: number;
  retryFailures: number;
  processedTaskIds: string[];
}

const defaultMetrics = (): UxMetrics => ({
  firstOpenedAt: Date.now(),
  firstTaskSubmittedAt: 0,
  firstTaskCompletedAt: 0,
  firstTaskCompletionMs: 0,
  startAttempts: 0,
  startFailures: 0,
  postSubmitEditSessions: 0,
  retryAttempts: 0,
  retrySuccesses: 0,
  retryFailures: 0,
  processedTaskIds: [],
});

export function getUxMetrics(): UxMetrics {
  try {
    const raw = localStorage.getItem(METRICS_KEY);
    if (!raw) {
      const initial = defaultMetrics();
      localStorage.setItem(METRICS_KEY, JSON.stringify(initial));
      return initial;
    }
    return { ...defaultMetrics(), ...JSON.parse(raw) };
  } catch {
    return defaultMetrics();
  }
}

export function recordStartAttempt(): void {
  updateMetrics((metrics) => ({ ...metrics, startAttempts: metrics.startAttempts + 1 }));
}

export function recordStartFailure(): void {
  updateMetrics((metrics) => ({ ...metrics, startFailures: metrics.startFailures + 1 }));
}

export function recordTaskSubmitted(): void {
  updateMetrics((metrics) => ({
    ...metrics,
    firstTaskSubmittedAt: metrics.firstTaskSubmittedAt || Date.now(),
  }));
}

export function recordPostSubmitEditSession(): void {
  updateMetrics((metrics) => ({ ...metrics, postSubmitEditSessions: metrics.postSubmitEditSessions + 1 }));
}

export function recordRetryAttempt(): void {
  updateMetrics((metrics) => ({ ...metrics, retryAttempts: metrics.retryAttempts + 1 }));
}

export function recordQueueOutcomes(queue: QueueTaskStatus[]): void {
  updateMetrics((metrics) => {
    const processed = new Set(metrics.processedTaskIds);
    let next = { ...metrics };
    for (const item of queue) {
      if (processed.has(item.id) || !["completed", "completed_with_errors", "cancelled"].includes(item.status)) continue;
      processed.add(item.id);
      if (!next.firstTaskCompletedAt && item.taskKind === "批量混剪" && item.completed > 0) {
        const completedAt = Date.now();
        next.firstTaskCompletedAt = completedAt;
        next.firstTaskCompletionMs = completedAt - next.firstOpenedAt;
      }
      if (item.isRetry) {
        if (item.status === "completed" || (item.status === "completed_with_errors" && item.completed > 0)) {
          next.retrySuccesses += 1;
        } else {
          next.retryFailures += 1;
        }
      }
    }
    next.processedTaskIds = Array.from(processed).slice(-200);
    return next;
  });
}

export function resetUxMetrics(): void {
  const metrics = defaultMetrics();
  localStorage.setItem(METRICS_KEY, JSON.stringify(metrics));
  notifyMetrics();
}

export function onUxMetricsChange(listener: () => void): () => void {
  window.addEventListener(METRICS_EVENT, listener);
  return () => window.removeEventListener(METRICS_EVENT, listener);
}

function updateMetrics(updater: (metrics: UxMetrics) => UxMetrics, notify = true): void {
  const current = getUxMetrics();
  const next = updater(current);
  if (JSON.stringify(next) === JSON.stringify(current)) return;
  localStorage.setItem(METRICS_KEY, JSON.stringify(next));
  if (notify) notifyMetrics();
}

function notifyMetrics(): void {
  window.dispatchEvent(new Event(METRICS_EVENT));
}
