import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getDiagnostics, getRenderStatus, loadAuthState, scanMaterials, saveAuthState, startDedupTask, startOverlayTask, startRenderTask, startWatermarkTask } from "./lib/tauri";
import { checkForUpdates, loginAccount, logoutAccount, redeemCode, registerAccount, verifyAccount } from "./lib/authApi";
import { recordPostSubmitEditSession, recordQueueOutcomes, recordStartAttempt, recordStartFailure, recordTaskSubmitted } from "./lib/analytics";
import { ToastContainer, showToast } from "./components/Toast";
import { TitleBar } from "./components/TitleBar";
import { Sidebar } from "./components/Sidebar";
import { ForcedUpdateDialog } from "./components/ForcedUpdateDialog";
import { MixWorkflowPage, type ScanViewState } from "./pages/MixWorkflowPage";
const OverlayPage = lazy(() => import("./pages/OverlayPage").then(module => ({ default: module.OverlayPage })));
const WatermarkPage = lazy(() => import("./pages/WatermarkPage").then(module => ({ default: module.WatermarkPage })));
const DedupPage = lazy(() => import("./pages/DedupPage").then(module => ({ default: module.DedupPage })));
const PerformancePage = lazy(() => import("./pages/PerformancePage").then(module => ({ default: module.PerformancePage })));
const TasksPage = lazy(() => import("./pages/TasksPage").then(module => ({ default: module.TasksPage })));
const AuthPage = lazy(() => import("./pages/AuthPage").then(module => ({ default: module.AuthPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then(module => ({ default: module.SettingsPage })));
import { getEncoderOptions, recommendedEncoder } from "./lib/performance";
import type { AuthState, DedupConfig, Diagnostics, MaterialConfig, OverlayConfig, PageKey, PerformanceConfig, RenderTaskStatus, ScanSummary, UpdateInfo, WatermarkConfig } from "./types";

const LAST_MATERIALS_KEY = "video_mix_last_materials_v2";
const LAST_OVERLAY_KEY = "video_mix_last_overlay_v2";
const LAST_WATERMARK_KEY = "video_mix_last_watermark_v1";
const LAST_DEDUP_KEY = "video_mix_last_dedup_v1";
const LAST_PERFORMANCE_KEY = "video_mix_global_performance_v1";
const MEMBERSHIP_VERIFY_INTERVAL_MS = 30 * 60 * 1000;
const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000;

export const defaultAuth: AuthState = {
  serverUrl: "https://videomix.7cloudvps.com",
  username: "",
  token: "",
  active: false,
  plan: "none",
  planLabel: "未开通",
  expiresAt: "",
  sessionExpiresAt: "",
  deviceId: "",
  deviceName: "",
  deviceBoundAt: "",
  deviceRebindCooldownUntil: "",
  deviceRebindRemainingSeconds: 0,
};

export const defaultMaterials: MaterialConfig = {
  sourceFolder: "",
  outputFolder: "",
  segmentCount: 3,
  outputCount: 10,
  trimStartSeconds: 0.1,
  enableFirstVideo: false,
  firstVideoFolder: "",
  enableTopInsert: false,
  enableTailVideo: false,
  tailVideoFolder: "",
  enableBannerOverlay: false,
  bannerFile: "",
  allowRepeatInsideOneVideo: false,
  enableDedupWhenComboRepeated: true,
  keepAudio: true,
  cleanupTemp: true,
  encoder: "cpu_libx264",
  workers: 2,
  concurrencyMode: "manual",
  enableAutoNaming: false,
  namingUseSourceName: false,
  namingDate: new Date().toISOString().slice(0, 10).replace(/-/g, ""),
  namingPart1: "",
  namingPart2: "",
  namingPart3: "",
  namingPart4: "",
  namingSeqDigits: 4,
  conflictStrategy: "skip",
};

export const defaultOverlay: OverlayConfig = {
  frameFile: "",
  videoFiles: [],
  outputFolder: "",
  x: 140,
  y: 420,
  width: 800,
  height: 1050,
  mode: "cover",
  fps: 30,
  crf: 20,
  preset: "medium",
  keepAudio: true,
  lockAspect: true,
  encoder: "cpu_libx264",
  workers: 2,
  concurrencyMode: "auto",
  enableAutoNaming: true,
  namingUseSourceName: true,
  namingDate: new Date().toISOString().slice(0, 10).replace(/-/g, ""),
  namingPart1: "",
  namingPart2: "套框",
  namingPart3: "",
  namingPart4: "",
  namingSeqDigits: 4,
  conflictStrategy: "suffix",
};

export const defaultWatermark: WatermarkConfig = {
  sourceFolder: "",
  logoFile: "",
  outputFolder: "",
  widthPercent: 16,
  speed: 170,
  opacity: 0.9,
  keepAudio: true,
  encoder: "cpu_libx264",
  workers: 2,
  concurrencyMode: "manual",
  conflictStrategy: "skip",
};

export const defaultDedup: DedupConfig = {
  sourceFolder: "",
  outputFolder: "",
  randomBitrate: true,
  dropFrames: true,
  microSpeed: true,
  subtleFilter: true,
  keepAudio: true,
  encoder: "cpu_libx264",
  workers: 2,
  concurrencyMode: "manual",
  conflictStrategy: "skip",
};

export const defaultPerformance: PerformanceConfig = {
  encoder: "cpu_libx264",
  workers: 2,
  concurrencyMode: "auto",
};

const fallbackScan: ScanSummary = {
  mainCount: 0,
  firstCount: 0,
  topCount: 0,
  tailCount: 0,
  bannerDetected: "",
  maxUniqueCombos: 0,
};

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

const fallbackTaskStatus: RenderTaskStatus = {
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

export function App() {
  const [page, setPage] = useState<PageKey>("mix");
  const [auth, setAuth] = useState<AuthState>(defaultAuth);
  const [materials, setMaterials] = useState<MaterialConfig>(() => loadStoredConfig(LAST_MATERIALS_KEY, defaultMaterials));
  const [overlay, setOverlay] = useState<OverlayConfig>(() => loadStoredConfig(LAST_OVERLAY_KEY, defaultOverlay));
  const [watermark, setWatermark] = useState<WatermarkConfig>(() => loadStoredConfig(LAST_WATERMARK_KEY, defaultWatermark));
  const [dedup, setDedup] = useState<DedupConfig>(() => loadStoredConfig(LAST_DEDUP_KEY, defaultDedup));
  const [performance, setPerformance] = useState<PerformanceConfig>(() => loadStoredConfig(LAST_PERFORMANCE_KEY, defaultPerformance));
  const [scan, setScan] = useState<ScanSummary>(fallbackScan);
  const [scanState, setScanState] = useState<ScanViewState>({ status: "idle", message: "" });
  const [diagnostics, setDiagnostics] = useState<Diagnostics>(fallbackDiagnostics);
  const [diagnosticsReady, setDiagnosticsReady] = useState(false);
  const [taskStatus, setTaskStatus] = useState<RenderTaskStatus>(fallbackTaskStatus);
  const [compact, setCompact] = useState(false);
  const [queueSubmitting, setQueueSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [authAction, setAuthAction] = useState<"login" | "register" | "verify" | "redeem" | null>(null);
  const [authError, setAuthError] = useState("");
  const [currentVersion, setCurrentVersion] = useState("0.2.3");
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateError, setUpdateError] = useState("");
  const scanRequestRef = useRef(0);
  const periodicVerifyRunningRef = useRef(false);
  const lastPeriodicVerifyErrorRef = useRef("");
  const hadStoredPerformanceRef = useRef(localStorage.getItem(LAST_PERFORMANCE_KEY) !== null);
  const taskSubmittedRef = useRef(false);
  const editSessionRecordedRef = useRef(false);
  const scanKey = useMemo(() => JSON.stringify({
    sourceFolder: materials.sourceFolder,
    segmentCount: materials.segmentCount,
    allowRepeatInsideOneVideo: materials.allowRepeatInsideOneVideo,
    enableFirstVideo: materials.enableFirstVideo,
    firstVideoFolder: materials.firstVideoFolder,
    enableTopInsert: materials.enableTopInsert,
    enableTailVideo: materials.enableTailVideo,
    tailVideoFolder: materials.tailVideoFolder,
    enableBannerOverlay: materials.enableBannerOverlay,
    bannerFile: materials.bannerFile,
  }), [materials]);

  useEffect(() => {
    getDiagnostics()
      .then((result) => {
        setDiagnostics(result);
        setPerformance((current) => {
          const recommended = recommendedEncoder(result);
          const selected = getEncoderOptions(result).find((item) => item.key === current.encoder);
          if (!hadStoredPerformanceRef.current) {
            return { encoder: recommended, concurrencyMode: "auto", workers: Math.min(4, Math.max(1, result.recommendedWorkers || 1)) };
          }
          return selected?.available === false ? { ...current, encoder: recommended } : current;
        });
      })
      .catch(() => setDiagnostics(fallbackDiagnostics))
      .finally(() => setDiagnosticsReady(true));
    loadAuthState()
      .then(async (stored) => {
        const merged = { ...defaultAuth, ...stored, serverUrl: stored.serverUrl || defaultAuth.serverUrl };
        setAuth({ ...merged, active: false });
        if (!merged.token) return;
        setAuthAction("verify");
        try {
          const patch = await verifyAccount(merged.serverUrl, merged.token, currentVersion);
          const verified = { ...merged, ...patch, token: merged.token };
          setAuth(verified);
          await saveAuthState(verified);
        } catch (error) {
          const message = readableError(error);
          const next = isInvalidSessionMessage(message)
            ? { ...merged, token: "", active: false, sessionExpiresAt: "" }
            : { ...merged, active: false };
          setAuth(next);
          setAuthError(`自动验证失败：${message}`);
          await saveAuthState(next).catch(() => undefined);
        } finally {
          setAuthAction(null);
        }
      })
      .catch(() => setAuthError("无法读取本地登录状态"));
    getRenderStatus().then(setTaskStatus).catch(() => undefined);
  }, []);

  const checkUpdates = useCallback(async (announce = false) => {
    setUpdateChecking(true);
    setUpdateError("");
    try {
      let version = "0.2.3";
      if ("__TAURI_INTERNALS__" in window) {
        const { getVersion } = await import("@tauri-apps/api/app");
        version = await getVersion();
      }
      setCurrentVersion(version);
      const info = await checkForUpdates(auth.serverUrl, version);
      setUpdateInfo(info);
      if (announce) showToast(info.updateAvailable ? "info" : "success", info.updateAvailable ? `发现新版本 ${info.latestVersion}` : "当前已是最新版");
    } catch (error) {
      const message = readableError(error);
      setUpdateError(message);
      if (announce) showToast("warning", `检查更新失败：${message}`);
    } finally {
      setUpdateChecking(false);
    }
  }, [auth.serverUrl]);

  useEffect(() => {
    void checkUpdates(false);
    const timer = window.setInterval(() => { void checkUpdates(false); }, UPDATE_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [checkUpdates]);

  useEffect(() => {
    if (page !== "tasks" && !taskStatus.running && taskStatus.pendingCount <= 0) return;
    let disposed = false;
    let timer = 0;
    const poll = async () => {
      try {
        const result = await getRenderStatus();
        if (!disposed) setTaskStatus(current => JSON.stringify(current) === JSON.stringify(result) ? current : result);
      } catch { /* Keep the last known state and retry. */ }
      if (!disposed) timer = window.setTimeout(poll, taskStatus.running || taskStatus.pendingCount > 0 ? 1000 : 5000);
    };
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [page, taskStatus.pendingCount, taskStatus.running]);

  useEffect(() => {
    if (!auth.token) return;

    const token = auth.token;
    const serverUrl = auth.serverUrl;
    const verifyMembership = async () => {
      if (periodicVerifyRunningRef.current) return;
      periodicVerifyRunningRef.current = true;
      try {
        const patch = await verifyAccount(serverUrl, token, currentVersion);
        setAuth((current) => {
          if (current.token !== token || current.serverUrl !== serverUrl) return current;
          const next = { ...current, ...patch, token };
          saveAuthState(next).catch(() => undefined);
          return next;
        });
        lastPeriodicVerifyErrorRef.current = "";
        setAuthError("");
      } catch (error) {
        const message = readableError(error);
        setAuth((current) => {
          if (current.token !== token || current.serverUrl !== serverUrl) return current;
          const next = isInvalidSessionMessage(message)
            ? { ...current, token: "", active: false, sessionExpiresAt: "" }
            : { ...current, active: false };
          saveAuthState(next).catch(() => undefined);
          return next;
        });
        setAuthError(`定期验证失败：${message}`);
        if (lastPeriodicVerifyErrorRef.current !== message) {
          lastPeriodicVerifyErrorRef.current = message;
          showToast("warning", `会员状态验证失败：${message}`);
        }
      } finally {
        periodicVerifyRunningRef.current = false;
      }
    };

    const timer = window.setInterval(() => { void verifyMembership(); }, MEMBERSHIP_VERIFY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [auth.serverUrl, auth.token, currentVersion]);

  useEffect(() => {
    const requestId = ++scanRequestRef.current;
    if (!materials.sourceFolder.trim()) {
      setScan(fallbackScan);
      setScanState({ status: "idle", message: "" });
      return;
    }
    setScanState({ status: "scanning", message: "正在扫描视频素材…" });
    const timer = window.setTimeout(() => {
      scanMaterials(materials)
        .then((result) => {
          if (scanRequestRef.current !== requestId) return;
          setScan(result);
          setScanState({ status: "ready", message: "扫描完成" });
        })
        .catch((error) => {
          if (scanRequestRef.current !== requestId) return;
          setScan(fallbackScan);
          setScanState({ status: "error", message: `扫描失败：${readableError(error)}` });
        });
    }, 320);
    return () => {
      window.clearTimeout(timer);
      if (scanRequestRef.current === requestId) scanRequestRef.current++;
    };
  }, [scanKey]);

  useEffect(() => {
    const timer = window.setTimeout(() => localStorage.setItem(LAST_MATERIALS_KEY, JSON.stringify(materials)), 250);
    return () => window.clearTimeout(timer);
  }, [materials]);

  useEffect(() => {
    const timer = window.setTimeout(() => localStorage.setItem(LAST_OVERLAY_KEY, JSON.stringify(overlay)), 250);
    return () => window.clearTimeout(timer);
  }, [overlay]);

  useEffect(() => {
    const timer = window.setTimeout(() => localStorage.setItem(LAST_WATERMARK_KEY, JSON.stringify(watermark)), 250);
    return () => window.clearTimeout(timer);
  }, [watermark]);

  useEffect(() => {
    const timer = window.setTimeout(() => localStorage.setItem(LAST_DEDUP_KEY, JSON.stringify(dedup)), 250);
    return () => window.clearTimeout(timer);
  }, [dedup]);

  useEffect(() => {
    const timer = window.setTimeout(() => localStorage.setItem(LAST_PERFORMANCE_KEY, JSON.stringify(performance)), 250);
    return () => window.clearTimeout(timer);
  }, [performance]);

  useEffect(() => {
    const patch = { encoder: performance.encoder, workers: performance.workers, concurrencyMode: performance.concurrencyMode };
    setMaterials((current) => current.encoder === patch.encoder && current.workers === patch.workers && current.concurrencyMode === patch.concurrencyMode ? current : { ...current, ...patch });
    setOverlay((current) => current.encoder === patch.encoder && current.workers === patch.workers && current.concurrencyMode === patch.concurrencyMode ? current : { ...current, ...patch });
    setWatermark((current) => current.encoder === patch.encoder && current.workers === patch.workers && current.concurrencyMode === patch.concurrencyMode ? current : { ...current, ...patch });
    setDedup((current) => current.encoder === patch.encoder && current.workers === patch.workers && current.concurrencyMode === patch.concurrencyMode ? current : { ...current, ...patch });
  }, [performance]);

  useEffect(() => {
    recordQueueOutcomes(taskStatus.queue);
  }, [taskStatus.queue]);

  useEffect(() => {
    const handleResize = () => setCompact(window.innerWidth < 1024);
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const persistAuth = useCallback(async (next: AuthState) => {
    await saveAuthState(next);
    setAuth(next);
  }, []);

  const handleAuthChange = useCallback((next: AuthState) => {
    void persistAuth(next).catch(error => {
      const message = `无法保存登录设置：${readableError(error)}`;
      setAuthError(message);
      showToast("danger", message);
    });
  }, [persistAuth]);

  const updateMaterials = useCallback((patch: Partial<MaterialConfig>) => {
    setSubmitError("");
    if (taskSubmittedRef.current && !editSessionRecordedRef.current) {
      editSessionRecordedRef.current = true;
      recordPostSubmitEditSession();
    }
    setMaterials((current) => ({ ...current, ...patch }));
  }, []);

  const updateOverlay = useCallback((patch: Partial<OverlayConfig>) => {
    setSubmitError("");
    setOverlay((current) => ({ ...current, ...patch }));
  }, []);

  const updateWatermark = useCallback((patch: Partial<WatermarkConfig>) => {
    setSubmitError("");
    setWatermark((current) => ({ ...current, ...patch }));
  }, []);

  const updateDedup = useCallback((patch: Partial<DedupConfig>) => {
    setSubmitError("");
    setDedup((current) => ({ ...current, ...patch }));
  }, []);

  const updatePerformance = useCallback((patch: Partial<PerformanceConfig>) => {
    setSubmitError("");
    setPerformance((current) => ({ ...current, ...patch, workers: Math.min(4, Math.max(1, patch.workers ?? current.workers)) }));
  }, []);

  const handleLogin = useCallback(async (username: string, password: string) => {
    setAuthError("");
    setAuthAction("login");
    try {
      const patch = await loginAccount(auth.serverUrl, username, password, currentVersion);
      const next = { ...auth, ...patch, username: patch.username || username };
      await persistAuth(next);
      showToast(next.active ? "success" : "warning", next.active ? "会员验证通过" : "账号已登录，请使用兑换码开通");
    } catch (error) {
      const message = readableError(error);
      setAuthError(message);
      showToast("danger", message);
    } finally {
      setAuthAction(null);
    }
  }, [auth, currentVersion, persistAuth]);

  const handleRegister = useCallback(async (username: string, password: string) => {
    setAuthError("");
    setAuthAction("register");
    try {
      await registerAccount(auth.serverUrl, username, password, currentVersion);
      const patch = await loginAccount(auth.serverUrl, username, password, currentVersion);
      const next = { ...auth, ...patch, username: patch.username || username };
      await persistAuth(next);
      showToast(next.active ? "success" : "warning", next.active ? "注册并登录成功" : "注册成功，请使用兑换码开通会员");
    } catch (error) {
      const message = readableError(error);
      setAuthError(message);
      showToast("danger", message);
    } finally {
      setAuthAction(null);
    }
  }, [auth, currentVersion, persistAuth]);

  const handleRedeem = useCallback(async (code: string) => {
    if (!auth.token) { showToast("warning", "请先登录账号"); return; }
    setAuthError("");
    setAuthAction("redeem");
    try {
      const patch = await redeemCode(auth.serverUrl, auth.token, code, currentVersion);
      const verified = await verifyAccount(auth.serverUrl, auth.token, currentVersion).catch(() => ({}));
      const next = { ...auth, ...patch, ...verified, token: auth.token };
      await persistAuth(next);
      showToast("success", "会员已开通");
    } catch (error) {
      const message = readableError(error);
      setAuthError(message);
      showToast("danger", message);
    } finally {
      setAuthAction(null);
    }
  }, [auth, currentVersion, persistAuth]);

  const handleVerify = useCallback(async () => {
    if (!auth.token) { showToast("warning", "请先登录"); return; }
    setAuthError("");
    setAuthAction("verify");
    try {
      const patch = await verifyAccount(auth.serverUrl, auth.token, currentVersion);
      const next = { ...auth, ...patch, token: auth.token };
      await persistAuth(next);
      showToast("success", next.active ? "会员状态有效" : "未开通会员");
    } catch (error) {
      const message = readableError(error);
      setAuthError(message);
      if (isInvalidSessionMessage(message)) {
        await persistAuth({ ...auth, token: "", active: false, sessionExpiresAt: "" });
      } else {
        setAuth((current) => ({ ...current, active: false }));
      }
      showToast("danger", message);
    } finally {
      setAuthAction(null);
    }
  }, [auth, currentVersion, persistAuth]);

  const handleLogout = useCallback(async () => {
    const previous = auth;
    const next = { ...defaultAuth, serverUrl: auth.serverUrl };
    try {
      await persistAuth(next);
    } catch (error) {
      const message = `无法清除本地登录状态：${readableError(error)}`;
      setAuthError(message);
      showToast("danger", message);
      return;
    }
    setAuthError("");
    showToast("info", "已退出登录");
    if (previous.token) {
      logoutAccount(previous.serverUrl, previous.token).catch(() => {
        showToast("warning", "本机已退出，但服务器注销未确认；登录会话仍会自动过期");
      });
    }
  }, [auth, persistAuth]);

  const startTask = useCallback(async () => {
    if (queueSubmitting) return;
    recordStartAttempt();
    const taskConfig = { ...materials, ...performance };
    const validationError = validateRenderStart(auth.active, taskConfig, scan, scanState, diagnosticsReady, diagnostics);
    if (validationError) {
      recordStartFailure();
      setSubmitError(validationError);
      if (!auth.active) setPage("auth");
      showToast("warning", validationError);
      return;
    }
    setSubmitError("");
    setQueueSubmitting(true);
    try {
      const status = await startRenderTask(taskConfig);
      setTaskStatus(status);
      recordTaskSubmitted();
      taskSubmittedRef.current = true;
      editSessionRecordedRef.current = false;
      const unfinished = status.queue.filter((item) => item.status === "waiting" || item.status === "running" || item.status === "cancelling").length;
      showToast("success", `已加入任务队列，当前共有 ${unfinished} 个未完成任务`);
    } catch (error) {
      const message = readableError(error);
      recordStartFailure();
      setSubmitError(message);
      showToast("danger", message);
    } finally {
      setQueueSubmitting(false);
    }
  }, [auth.active, diagnostics, diagnosticsReady, materials, performance, queueSubmitting, scan, scanState]);

  const startOverlay = useCallback(async () => {
    if (queueSubmitting) return;
    recordStartAttempt();
    const taskConfig = { ...overlay, ...performance };
    const validationError = validateOverlayStart(auth.active, taskConfig, diagnosticsReady, diagnostics);
    if (validationError) {
      recordStartFailure();
      setSubmitError(validationError);
      if (!auth.active) setPage("auth");
      showToast("warning", validationError);
      return;
    }
    setSubmitError("");
    setQueueSubmitting(true);
    try {
      const status = await startOverlayTask(taskConfig);
      setTaskStatus(status);
      recordTaskSubmitted();
      const unfinished = status.queue.filter((item) => item.status === "waiting" || item.status === "running" || item.status === "cancelling").length;
      showToast("success", `套外框任务已加入队列，当前共有 ${unfinished} 个未完成任务`);
    } catch (error) {
      const message = readableError(error);
      recordStartFailure();
      setSubmitError(message);
      setTaskStatus({
        ...fallbackTaskStatus,
        status: "启动失败",
        failed: 1,
        total: 1,
        progress: 100,
        taskKind: "视频套外框",
        logs: ["套外框任务启动失败。", message],
      });
      showToast("danger", message);
    } finally {
      setQueueSubmitting(false);
    }
  }, [auth.active, diagnostics, diagnosticsReady, overlay, performance, queueSubmitting]);

  const startWatermark = useCallback(async () => {
    if (queueSubmitting) return;
    recordStartAttempt();
    const taskConfig = { ...watermark, ...performance };
    const validationError = validateWatermarkStart(auth.active, taskConfig, diagnosticsReady, diagnostics);
    if (validationError) {
      recordStartFailure();
      setSubmitError(validationError);
      if (!auth.active) setPage("auth");
      showToast("warning", validationError);
      return;
    }
    setSubmitError("");
    setQueueSubmitting(true);
    try {
      const status = await startWatermarkTask(taskConfig);
      setTaskStatus(status);
      recordTaskSubmitted();
      const unfinished = status.queue.filter((item) => item.status === "waiting" || item.status === "running" || item.status === "cancelling").length;
      showToast("success", `飘动水印任务已加入队列，当前共有 ${unfinished} 个未完成任务`);
    } catch (error) {
      const message = readableError(error);
      recordStartFailure();
      setSubmitError(message);
      showToast("danger", message);
    } finally {
      setQueueSubmitting(false);
    }
  }, [auth.active, diagnostics, diagnosticsReady, performance, queueSubmitting, watermark]);

  const startDedup = useCallback(async () => {
    if (queueSubmitting) return;
    recordStartAttempt();
    const taskConfig = { ...dedup, ...performance };
    const validationError = validateDedupStart(auth.active, taskConfig, diagnosticsReady, diagnostics);
    if (validationError) {
      recordStartFailure();
      setSubmitError(validationError);
      if (!auth.active) setPage("auth");
      showToast("warning", validationError);
      return;
    }
    setSubmitError("");
    setQueueSubmitting(true);
    try {
      const status = await startDedupTask(taskConfig);
      setTaskStatus(status);
      recordTaskSubmitted();
      const unfinished = status.queue.filter((item) => item.status === "waiting" || item.status === "running" || item.status === "cancelling").length;
      showToast("success", `视频去重任务已加入队列，当前共有 ${unfinished} 个未完成任务`);
    } catch (error) {
      const message = readableError(error);
      recordStartFailure();
      setSubmitError(message);
      showToast("danger", message);
    } finally {
      setQueueSubmitting(false);
    }
  }, [auth.active, dedup, diagnostics, diagnosticsReady, performance, queueSubmitting]);

  const forceUpdate = Boolean(updateInfo?.required);

  return (
    <div className={`${compact ? "app-shell compact" : "app-shell"}${forceUpdate ? " force-update" : ""}`}>
      <TitleBar blocked={forceUpdate} />
      <Sidebar page={page} onChange={setPage} auth={auth} pendingTasks={taskStatus.pendingCount + (taskStatus.running ? 1 : 0)} updateInfo={updateInfo} blocked={forceUpdate} />
      <main className="content-viewport" inert={forceUpdate ? true : undefined} aria-hidden={forceUpdate || undefined}>
        <div className="content-inner">
          <Suspense fallback={<div className="panel" role="status">正在加载页面…</div>}>
          {page === "mix" && (
            <MixWorkflowPage
              materials={materials}
              scan={scan}
              scanState={scanState}
              diagnostics={diagnostics}
              diagnosticsReady={diagnosticsReady}
              authActive={auth.active}
              submitting={queueSubmitting}
              submitError={submitError}
              taskStatus={taskStatus}
              onUpdate={updateMaterials}
              onStart={startTask}
              onOpenAuth={() => setPage("auth")}
              onOpenTasks={() => setPage("tasks")}
              onOpenPerformance={() => setPage("performance")}
            />
          )}
          {page === "overlay" && <OverlayPage config={overlay} submitting={queueSubmitting} submitError={submitError} onUpdate={updateOverlay} onStart={startOverlay} onOpenPerformance={() => setPage("performance")} />}
          {page === "watermark" && <WatermarkPage config={watermark} diagnostics={diagnostics} diagnosticsReady={diagnosticsReady} submitting={queueSubmitting} submitError={submitError} taskStatus={taskStatus} onUpdate={updateWatermark} onStart={startWatermark} onOpenTasks={() => setPage("tasks")} onOpenPerformance={() => setPage("performance")} />}
          {page === "dedup" && <DedupPage config={dedup} diagnostics={diagnostics} diagnosticsReady={diagnosticsReady} submitting={queueSubmitting} submitError={submitError} taskStatus={taskStatus} onUpdate={updateDedup} onStart={startDedup} onOpenTasks={() => setPage("tasks")} onOpenPerformance={() => setPage("performance")} />}
          {page === "performance" && <PerformancePage config={performance} diagnostics={diagnostics} diagnosticsReady={diagnosticsReady} onUpdate={updatePerformance} />}
          {page === "tasks" && <TasksPage status={taskStatus} onStatusChange={setTaskStatus} />}
          {page === "auth" && (
            <AuthPage auth={auth} action={authAction} error={authError} onAuthChange={(next) => { setAuthError(""); setAuth(next); }} onLogin={handleLogin} onRegister={handleRegister} onRedeem={handleRedeem} onVerify={handleVerify} onLogout={handleLogout} />
          )}
          {page === "settings" && (
            <SettingsPage auth={auth} diagnostics={diagnostics} diagnosticsReady={diagnosticsReady} currentVersion={currentVersion} updateInfo={updateInfo} updateChecking={updateChecking} updateError={updateError} onCheckUpdates={() => void checkUpdates(true)} onAuthChange={handleAuthChange} onLogout={handleLogout} />
          )}
          </Suspense>
        </div>
      </main>
      {updateInfo?.required && (
        <ForcedUpdateDialog
          currentVersion={currentVersion}
          updateInfo={updateInfo}
          checking={updateChecking}
          error={updateError}
          onRetry={() => void checkUpdates(true)}
        />
      )}
      <ToastContainer />
    </div>
  );
}

function readableError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "操作失败";
}

function isInvalidSessionMessage(message: string): boolean {
  return /登录已(?:过期|失效)|请重新登录|其他设备登录/.test(message);
}

function loadStoredConfig<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function validateRenderStart(
  active: boolean,
  materials: MaterialConfig,
  scan: ScanSummary,
  scanState: ScanViewState,
  diagnosticsReady: boolean,
  diagnostics: Diagnostics,
): string {
  if (!active) return "请先登录会员账号";
  if (!materials.sourceFolder.trim()) return "请先选择素材目录";
  if (scanState.status === "scanning") return "素材仍在扫描，请稍候";
  if (scanState.status === "error") return scanState.message || "素材扫描失败";
  if (scan.mainCount <= 0) return "当前素材目录没有可用主素材";
  if (materials.segmentCount <= 0 || materials.outputCount <= 0) return "生成参数必须大于 0";
  if (!materials.allowRepeatInsideOneVideo && materials.segmentCount > scan.mainCount) return "每条主素材数不能大于主素材数量";
  if (diagnosticsReady && !diagnostics.hasFfmpeg) return "找不到 FFmpeg，请先在设置页确认组件状态";
  return "";
}

function validateOverlayStart(active: boolean, overlay: OverlayConfig, diagnosticsReady: boolean, diagnostics: Diagnostics): string {
  if (!active) return "请先登录会员账号";
  if (!overlay.frameFile.trim()) return "请先选择外框图片";
  if (overlay.videoFiles.length <= 0) return "请先选择视频";
  if (overlay.width <= 0 || overlay.height <= 0) return "视频区域宽高必须大于 0";
  if (diagnosticsReady && !diagnostics.hasFfmpeg) return "找不到 FFmpeg，请先在设置页确认组件状态";
  return "";
}

function validateWatermarkStart(active: boolean, watermark: WatermarkConfig, diagnosticsReady: boolean, diagnostics: Diagnostics): string {
  if (!active) return "请先登录会员账号";
  if (!watermark.sourceFolder.trim()) return "请先选择视频文件夹";
  if (!watermark.logoFile.trim()) return "请先选择 Logo 图片";
  if (watermark.widthPercent < 5 || watermark.widthPercent > 35) return "Logo 宽度占比需要在 5% - 35% 之间";
  if (watermark.speed < 40 || watermark.speed > 600) return "飘动速度需要在 40 - 600 px/秒之间";
  if (watermark.opacity < 0.1 || watermark.opacity > 1) return "透明度需要在 0.1 - 1.0 之间";
  if (diagnosticsReady && !diagnostics.hasFfmpeg) return "找不到 FFmpeg，请先在设置页确认组件状态";
  return "";
}

function validateDedupStart(active: boolean, dedup: DedupConfig, diagnosticsReady: boolean, diagnostics: Diagnostics): string {
  if (!active) return "请先登录会员账号";
  if (!dedup.sourceFolder.trim()) return "请先选择视频文件夹";
  if (!dedup.randomBitrate && !dedup.dropFrames && !dedup.microSpeed && !dedup.subtleFilter) return "请至少开启一种去重处理方式";
  if (dedup.workers < 1 || dedup.workers > 4) return "并发处理需要在 1 - 4 路之间";
  if (diagnosticsReady && !diagnostics.hasFfmpeg) return "找不到 FFmpeg，请先在设置页确认组件状态";
  return "";
}
