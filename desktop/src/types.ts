import type { ComponentType } from "react";

export type PageKey = "mix" | "overlay" | "watermark" | "dedup" | "performance" | "tasks" | "auth" | "settings";
export type PlanKey = "month" | "quarter" | "half_year" | "year" | "permanent" | "none";
export type EncoderKey = "cpu_libx264" | "intel_qsv" | "nvidia_nvenc" | "amd_amf" | "mixed_intel" | "mixed_nvidia" | "mixed_amd";
export type ConflictStrategy = "skip" | "overwrite" | "suffix";
export type ConcurrencyMode = "manual" | "auto" | "safe";
export type ToastTone = "success" | "warning" | "danger" | "info";
export type ServerConnectionStatus = "checking" | "connected" | "failed";

export interface PerformanceConfig {
  encoder: EncoderKey;
  workers: number;
  concurrencyMode: ConcurrencyMode;
}

export interface AuthState {
  serverUrl: string;
  username: string;
  token: string;
  active: boolean;
  plan: PlanKey;
  planLabel: string;
  expiresAt: string;
  sessionExpiresAt: string;
  deviceId: string;
  deviceName: string;
  deviceBoundAt: string;
  deviceRebindCooldownUntil: string;
  deviceRebindRemainingSeconds: number;
}

export interface ServerHealth {
  ok: boolean;
  status: string;
  time: string;
}

export interface UpdateInfo {
  channel: string;
  currentVersion: string;
  latestVersion: string;
  minimumVersion: string;
  updateAvailable: boolean;
  required: boolean;
  title: string;
  notes: string;
  downloadUrl: string;
  sha256: string;
  updatedAt: string;
}

export interface MaterialConfig {
  sourceFolder: string;
  outputFolder: string;
  segmentCount: number;
  outputCount: number;
  trimStartSeconds: number;
  enableFirstVideo: boolean;
  firstVideoFolder: string;
  enableTopInsert: boolean;
  enableTailVideo: boolean;
  tailVideoFolder: string;
  enableBannerOverlay: boolean;
  bannerFile: string;
  allowRepeatInsideOneVideo: boolean;
  enableDedupWhenComboRepeated: boolean;
  keepAudio: boolean;
  cleanupTemp: boolean;
  encoder: EncoderKey;
  workers: number;
  concurrencyMode: ConcurrencyMode;
  enableAutoNaming: boolean;
  namingUseSourceName: boolean;
  namingDate: string;
  namingPart1: string;
  namingPart2: string;
  namingPart3: string;
  namingPart4: string;
  namingSeqDigits: number;
  conflictStrategy: ConflictStrategy;
}

export interface OverlayConfig {
  frameFile: string;
  videoFiles: string[];
  outputFolder: string;
  x: number;
  y: number;
  width: number;
  height: number;
  mode: "cover" | "contain";
  fps: number;
  crf: number;
  preset: "ultrafast" | "superfast" | "veryfast" | "faster" | "fast" | "medium" | "slow";
  keepAudio: boolean;
  lockAspect: boolean;
  encoder: string;
  workers: number;
  concurrencyMode: string;
  enableAutoNaming: boolean;
  namingUseSourceName: boolean;
  namingDate: string;
  namingPart1: string;
  namingPart2: string;
  namingPart3: string;
  namingPart4: string;
  namingSeqDigits: number;
  conflictStrategy: ConflictStrategy;
}

export interface WatermarkConfig {
  sourceFolder: string;
  logoFile: string;
  outputFolder: string;
  widthPercent: number;
  speed: number;
  opacity: number;
  keepAudio: boolean;
  encoder: string;
  workers: number;
  concurrencyMode: ConcurrencyMode;
  conflictStrategy: ConflictStrategy;
}

export interface DedupConfig {
  sourceFolder: string;
  outputFolder: string;
  randomBitrate: boolean;
  dropFrames: boolean;
  microSpeed: boolean;
  subtleFilter: boolean;
  keepAudio: boolean;
  encoder: string;
  workers: number;
  concurrencyMode: ConcurrencyMode;
  conflictStrategy: ConflictStrategy;
}

export interface ScanSummary {
  mainCount: number;
  firstCount: number;
  topCount: number;
  tailCount: number;
  bannerDetected: string;
  maxUniqueCombos: number;
}

export interface Diagnostics {
  ffmpegPath: string;
  ffprobePath: string;
  hasFfmpeg: boolean;
  hasFfprobe: boolean;
  hasQsv: boolean;
  hasScaleQsv: boolean;
  hasVppQsv: boolean;
  hasNvenc: boolean;
  hasAmf: boolean;
  recommendedWorkers: number;
}

export interface RenderTaskStatus {
  running: boolean;
  cancelled: boolean;
  status: string;
  progress: number;
  completed: number;
  failed: number;
  total: number;
  outputFolder: string;
  taskKind: string;
  logs: string[];
  currentTaskId: string;
  pendingCount: number;
  queue: QueueTaskStatus[];
}

export interface QueueTaskStatus {
  id: string;
  name: string;
  taskKind: string;
  status: "waiting" | "running" | "cancelling" | "completed" | "completed_with_errors" | "cancelled";
  progress: number;
  completed: number;
  failed: number;
  total: number;
  outputFolder: string;
  createdAt: number;
  isRetry: boolean;
}

export interface Toast {
  id: string;
  tone: ToastTone;
  message: string;
}

export type IconProps = {
  size?: number | string;
  strokeWidth?: number | string;
  className?: string;
};
