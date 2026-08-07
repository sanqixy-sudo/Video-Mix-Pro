import type { AuthState, ServerHealth, UpdateInfo } from "../types";

const REQUEST_TIMEOUT_MS = 8_000;

type AuthResponse = {
  active?: boolean;
  username?: string;
  token?: string;
  plan?: string;
  plan_label?: string;
  expires_at?: string;
  session_expires_at?: string;
  device_id?: string;
  device_name?: string;
  device_bound_at?: string;
  device_rebind_cooldown_until?: string;
  device_rebind_remaining_seconds?: number;
  detail?: string | { code?: string; message?: string; remaining_seconds?: number; cooldown_until?: string };
  error?: string;
};

export function getOrCreateDeviceId(): string {
  const key = "video-mix-pro-device-id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;
  const id = crypto.randomUUID().replaceAll("-", "");
  localStorage.setItem(key, id);
  return id;
}

export function deviceName(): string {
  return "Windows-PC";
}

export async function registerAccount(serverUrl: string, username: string, password: string): Promise<void> {
  await apiPost(serverUrl, "/api/auth/register", { username, password });
}

export async function loginAccount(serverUrl: string, username: string, password: string): Promise<Partial<AuthState>> {
  const data = await apiPost(serverUrl, "/api/auth/login", {
    username,
    password,
    device_id: getOrCreateDeviceId(),
    device_name: deviceName(),
  });
  return normalizeAuth(data, serverUrl, username);
}

export async function verifyAccount(serverUrl: string, token: string): Promise<Partial<AuthState>> {
  const data = await apiPost(serverUrl, "/api/auth/verify", {
    token,
    device_id: getOrCreateDeviceId(),
  });
  return normalizeAuth(data, serverUrl, data.username || "");
}

export async function redeemCode(serverUrl: string, token: string, code: string): Promise<Partial<AuthState>> {
  const data = await apiPost(serverUrl, "/api/redeem", {
    token,
    device_id: getOrCreateDeviceId(),
    code,
  });
  return normalizeAuth(data, serverUrl, data.username || "");
}

export async function logoutAccount(serverUrl: string, token: string): Promise<void> {
  await apiPost(serverUrl, "/api/auth/logout", {
    token,
    device_id: getOrCreateDeviceId(),
  });
}

export async function checkServerHealth(serverUrl: string): Promise<ServerHealth> {
  const data = await apiRequest(serverUrl, "/api/health", { method: "GET" });
  return {
    ok: Boolean(data.ok),
    status: String(data.status || "unknown"),
    time: String(data.time || ""),
  };
}

export async function checkForUpdates(serverUrl: string, currentVersion: string): Promise<UpdateInfo> {
  const query = new URLSearchParams({ current_version: currentVersion, channel: "stable", platform: "windows", arch: "x64" });
  const data = await apiRequest(serverUrl, `/api/update/check?${query.toString()}`, { method: "GET" });
  return {
    channel: String(data.channel || "stable"),
    currentVersion: String(data.current_version || currentVersion),
    latestVersion: String(data.latest_version || currentVersion),
    minimumVersion: String(data.minimum_version || data.latest_version || currentVersion),
    updateAvailable: Boolean(data.update_available),
    required: Boolean(data.required),
    title: String(data.title || ""),
    notes: String(data.notes || ""),
    downloadUrl: String(data.download_url || ""),
    sha256: String(data.sha256 || ""),
    updatedAt: String(data.updated_at || ""),
  };
}

async function apiPost(serverUrl: string, path: string, payload: Record<string, string>): Promise<AuthResponse> {
  return apiRequest(serverUrl, path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function apiRequest(serverUrl: string, path: string, init: RequestInit): Promise<AuthResponse & Record<string, unknown>> {
  const base = serverUrl.replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(base)) {
    throw new Error("服务器地址必须以 http:// 或 https:// 开头");
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, { ...init, signal: controller.signal });
    const raw = await response.text();
    let data: AuthResponse & Record<string, unknown> = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw };
      }
    }
    if (!response.ok) {
      const retryAfter = Number.parseInt(response.headers.get("Retry-After") || "", 10);
      if (response.status === 429 && Number.isFinite(retryAfter)) {
        throw new Error(`请求过于频繁，请 ${retryAfter} 秒后重试`);
      }
      const detail = data.detail;
      if (detail && typeof detail === "object" && detail.code === "DEVICE_REBIND_COOLDOWN") {
        const remaining = Number(detail.remaining_seconds || 0);
        throw new Error(`设备换绑冷却中，还需等待 ${formatRemainingTime(remaining)}。如需立即换绑，请联系管理员解除冷却。`);
      }
      const message = typeof detail === "string" ? detail : detail && typeof detail.message === "string" ? detail.message : "";
      throw new Error(message || data.error || `请求失败：HTTP ${response.status}`);
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("连接会员服务器超时，请检查网络后重试");
    }
    if (error instanceof TypeError) {
      throw new Error("无法连接会员服务器，请检查服务器地址或网络");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function normalizeAuth(data: AuthResponse, serverUrl: string, fallbackUsername: string): Partial<AuthState> {
  return {
    serverUrl,
    username: data.username || fallbackUsername,
    token: data.token || "",
    active: Boolean(data.active),
    plan: (data.plan || "none") as AuthState["plan"],
    planLabel: data.plan_label || data.plan || "未开通",
    expiresAt: data.expires_at || "",
    sessionExpiresAt: data.session_expires_at || "",
    deviceId: data.device_id || getOrCreateDeviceId(),
    deviceName: data.device_name || "",
    deviceBoundAt: data.device_bound_at || "",
    deviceRebindCooldownUntil: data.device_rebind_cooldown_until || "",
    deviceRebindRemainingSeconds: Number(data.device_rebind_remaining_seconds || 0),
  };
}

function formatRemainingTime(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.ceil((safe % 3600) / 60);
  if (hours && minutes) return `${hours} 小时 ${minutes} 分钟`;
  if (hours) return `${hours} 小时`;
  if (minutes) return `${minutes} 分钟`;
  return "片刻";
}
