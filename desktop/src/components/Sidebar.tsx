import {
  LayoutDashboard,
  Image,
  ListPlus,
  Video,
  Stamp,
  ShieldCheck,
  Settings,
} from "lucide-react";
import type { PageKey, AuthState } from "../types";

const navItems: Array<{ key: PageKey; label: string; icon: typeof LayoutDashboard }> = [
  { key: "mix", label: "批量混剪", icon: LayoutDashboard },
  { key: "overlay", label: "套外框", icon: Image },
  { key: "watermark", label: "飘动水印", icon: Stamp },
  { key: "dedup", label: "视频去重", icon: Video },
  { key: "tasks", label: "任务中心", icon: ListPlus },
  { key: "auth", label: "授权中心", icon: ShieldCheck },
  { key: "settings", label: "设置", icon: Settings },
];

export function Sidebar({ page, onChange, auth, pendingTasks }: { page: PageKey; onChange: (p: PageKey) => void; auth: AuthState; pendingTasks: number }) {
  return (
    <aside className="sidebar">
      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = page === item.key;
          return (
            <button
              key={item.key}
              className={`${active ? "nav-item active" : "nav-item"}${item.key === "tasks" ? " nav-system-start" : ""}`}
              title={item.label}
              onClick={() => onChange(item.key)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
              {item.key === "tasks" && pendingTasks > 0 && <span className="nav-badge">{pendingTasks}</span>}
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className={auth.active ? "dot" : "dot inactive"} />
        <span>{memberLabel(auth)}</span>
      </div>
    </aside>
  );
}

function memberLabel(auth: AuthState): string {
  if (!auth.active) return "未授权";
  const label = auth.plan === "permanent" || auth.planLabel.includes("永久") ? "永久会员" : "高级会员";
  if (label === "永久会员") return label;
  return auth.expiresAt ? `${label} 到期：${auth.expiresAt.slice(0, 10)}` : label;
}
