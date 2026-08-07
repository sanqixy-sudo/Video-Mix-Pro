import { invoke } from "@tauri-apps/api/core";
import type { AuthState, Diagnostics, MaterialConfig, OverlayConfig, RenderTaskStatus, ScanSummary, WatermarkConfig } from "../types";

const fallbackDiagnostics: Diagnostics = {
  ffmpegPath: "",
  ffprobePath: "",
  hasFfmpeg: false,
  hasFfprobe: false,
  hasQsv: false,
  hasScaleQsv: false,
  hasVppQsv: false,
  hasNvenc: false,
  hasAmf: false,
  recommendedWorkers: 2,
};

const fallbackRenderStatus: RenderTaskStatus = {
  running: false,
  cancelled: false,
  status: "就绪",
  progress: 0,
  completed: 0,
  failed: 0,
  total: 0,
  outputFolder: "",
  taskKind: "",
  logs: ["等待任务开始..."],
  currentTaskId: "",
  pendingCount: 0,
  queue: [],
};

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function getDiagnostics(): Promise<Diagnostics> {
  if (!isTauriRuntime()) return fallbackDiagnostics;
  return invoke<Diagnostics>("get_diagnostics");
}

export async function scanMaterials(config: MaterialConfig): Promise<ScanSummary> {
  if (!isTauriRuntime()) {
    return {
      mainCount: 0,
      firstCount: 0,
      topCount: 0,
      tailCount: 0,
      bannerDetected: "",
      maxUniqueCombos: 0,
    };
  }
  return invoke<ScanSummary>("scan_materials", { config });
}

export async function loadAuthState(): Promise<Partial<AuthState>> {
  if (!isTauriRuntime()) return {};
  return invoke<Partial<AuthState>>("load_auth_state");
}

export async function saveAuthState(auth: AuthState): Promise<void> {
  if (!isTauriRuntime()) return;
  await invoke("save_auth_state", { auth });
}

export async function pickDirectory(): Promise<string | null> {
  if (!isTauriRuntime()) return null;
  return invoke<string | null>("pick_directory");
}

export async function pickFile(kind?: "image" | "video" | "any"): Promise<string | null> {
  if (!isTauriRuntime()) return null;
  return invoke<string | null>("pick_file", { kind: kind || "any" });
}

export async function pickFiles(kind?: "image" | "video" | "any"): Promise<string[]> {
  if (!isTauriRuntime()) return [];
  return invoke<string[]>("pick_files", { kind: kind || "any" });
}

export async function openDirectory(path: string): Promise<void> {
  if (!isTauriRuntime()) return;
  await invoke("open_directory", { path });
}

export async function startRenderTask(config: MaterialConfig): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("start_render_task", { config });
}

export async function startOverlayTask(config: OverlayConfig): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("start_overlay_task", { config });
}

export async function startWatermarkTask(config: WatermarkConfig): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("start_watermark_task", { config });
}

export async function getRenderStatus(): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("get_render_status");
}

export async function cancelRenderTask(): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("cancel_render_task");
}

export async function removeQueuedTask(taskId: string): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("remove_queued_task", { taskId });
}

export async function clearPendingTasks(): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("clear_pending_tasks");
}

export async function clearFinishedTasks(): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("clear_finished_tasks");
}

export async function retryQueueTask(taskId: string): Promise<RenderTaskStatus> {
  if (!isTauriRuntime()) return fallbackRenderStatus;
  return invoke<RenderTaskStatus>("retry_queue_task", { taskId });
}
