import { useState } from "react";
import { CircleDot, Clock3, KeyRound, LogOut } from "lucide-react";
import type { AuthState } from "../types";
import brandHorizontal from "../assets/brand-horizontal-dark.png";

export function AuthPage({
  auth,
  action,
  error,
  onAuthChange,
  onLogin,
  onRegister,
  onRedeem,
  onVerify,
  onLogout,
}: {
  auth: AuthState;
  action: "login" | "register" | "verify" | "redeem" | null;
  error: string;
  onAuthChange: (a: AuthState) => void;
  onLogin: (u: string, p: string) => void;
  onRegister: (u: string, p: string) => void;
  onRedeem: (c: string) => void;
  onVerify: () => void;
  onLogout: () => void;
}) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const sessionExpired = Boolean(auth.sessionExpiresAt && new Date(auth.sessionExpiresAt).getTime() <= Date.now());

  if (auth.token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <img src={brandHorizontal} alt="Video Mix Pro" />
            <p>已登录</p>
          </div>

          <div className="member-card">
            <div className="member-card-header">
              <h3>{auth.username}</h3>
              <span className={auth.active ? "member-badge active" : "member-badge inactive"}>
                <CircleDot size={10} />
                {auth.active ? auth.planLabel : "未开通"}
              </span>
            </div>
            <div className="member-info">
              <span>
                <strong>会员到期</strong> {auth.plan === "permanent" ? "永久" : formatDateTime(auth.expiresAt, "未开通")}
              </span>
              <span className={sessionExpired ? "session-expired" : undefined}>
                <strong>登录会话</strong> {formatDateTime(auth.sessionExpiresAt, "由服务器管理")}
              </span>
              <span>
                <strong>设备</strong> {auth.deviceName || auth.deviceId}
              </span>
              {auth.deviceBoundAt && <span><strong>绑定时间</strong> {formatDateTime(auth.deviceBoundAt, "—")}</span>}
              {auth.deviceRebindRemainingSeconds > 0 && <span><strong>换绑保护</strong> 剩余 {formatCooldown(auth.deviceRebindRemainingSeconds)}</span>}
            </div>
          </div>

          {sessionExpired && (
            <div className="session-notice danger" role="alert">
              <Clock3 size={16} />
              <span><strong>登录已过期</strong>，请退出后重新登录。</span>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {error && <div className="form-error" role="alert">{error}</div>}
            <button className="btn btn-primary btn-block" onClick={onVerify} disabled={action !== null}>
              <KeyRound size={14} />
              {action === "verify" ? "正在验证..." : "刷新会员状态"}
            </button>
            <div className="input-field">
              <label>兑换码</label>
              <input type="text" value={code} onChange={(e) => setCode(e.target.value)} placeholder="输入兑换码，可用于续时长" />
            </div>
            <button className="btn btn-primary btn-block" onClick={() => onRedeem(code)} disabled={action !== null || !code.trim()}>
              {action === "redeem" ? "正在兑换..." : "使用兑换码"}
            </button>
            <button className="btn btn-ghost btn-block" onClick={onLogout} disabled={action !== null}>
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <img src={brandHorizontal} alt="Video Mix Pro" />
          <p>登录会员账号</p>
        </div>

        <div className="auth-tabs">
          <button className={tab === "login" ? "auth-tab active" : "auth-tab"} onClick={() => setTab("login")}>
            登录
          </button>
          <button className={tab === "register" ? "auth-tab active" : "auth-tab"} onClick={() => setTab("register")}>
            注册
          </button>
        </div>

        {error && <div className="form-error" role="alert">{error}</div>}

        {tab === "login" && (
          <>
            <div className="input-field">
              <label>账号</label>
              <input type="text" autoComplete="username" value={auth.username} onChange={(e) => onAuthChange({ ...auth, username: e.target.value })} placeholder="账号" />
            </div>
            <div className="input-field">
              <label>密码</label>
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" />
            </div>
            <button className="btn btn-primary btn-block btn-lg" disabled={action !== null || !auth.username.trim() || !password} onClick={() => onLogin(auth.username, password)}>
              {action === "login" || action === "verify" ? "正在登录..." : "登录"}
            </button>
          </>
        )}

        {tab === "register" && (
          <>
            <div className="input-field">
              <label>账号</label>
              <input type="text" autoComplete="username" value={auth.username} onChange={(e) => onAuthChange({ ...auth, username: e.target.value })} placeholder="账号" />
            </div>
            <div className="input-field">
              <label>密码</label>
              <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" />
            </div>
            <button className="btn btn-primary btn-block btn-lg" disabled={action !== null || !auth.username.trim() || !password} onClick={() => onRegister(auth.username, password)}>
              {action === "register" ? "正在注册..." : "注册并登录"}
            </button>
          </>
        )}

        <p className="auth-footer">兑换码需登录后使用，一个账号仅允许一台设备使用</p>
      </div>
    </div>
  );
}

function formatDateTime(value: string, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function formatCooldown(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.ceil((safe % 3600) / 60);
  return [hours ? `${hours} 小时` : "", minutes ? `${minutes} 分钟` : ""].filter(Boolean).join(" ") || "片刻";
}
