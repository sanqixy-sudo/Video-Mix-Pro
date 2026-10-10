import React, { lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { App, Button, ConfigProvider, Drawer, Modal, Skeleton } from "antd";
import zhCN from "antd/locale/zh_CN";
import "dayjs/locale/zh-cn";
import { api, setCsrf } from "./api";
import { dayjs, Failure } from "./shared";
import "./style.css";
dayjs.locale("zh-cn");
const Users = lazy(() => import("./pages/Users"));
const Codes = lazy(() => import("./pages/Codes"));
const Batches = lazy(() => import("./pages/Batches"));
const Overview = lazy(() => import("./pages/Overview"));
const Releases = lazy(() => import("./pages/Releases"));
const Site = lazy(() => import("./pages/Site"));
const Audit = lazy(() => import("./pages/Audit"));
const links = [
  ["users", "用户与会员", "01"],
  ["codes", "兑换码", "02"],
  ["batches", "兑换批次", "03"],
  ["overview", "工作台", "04"],
  ["releases", "版本发布", "05"],
  ["site", "官网设置", "06"],
  ["audit", "操作记录", "07"],
];
class Boundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <Failure
        message="页面加载失败，请重新加载。版本草稿会保留。"
        retry={() => window.location.reload()}
      />
    ) : (
      this.props.children
    );
  }
}
function Console() {
  const [mobile, setMobile] = useState(false);
  const [expired, setExpired] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const location = useLocation();
  const load = () => {
    setError("");
    api("/session")
      .then((s) => {
        setCsrf(s.csrf_token);
        setReady(true);
      })
      .catch((e) => setError(e.message));
  };
  useEffect(load, []);
  useEffect(() => {
    const handler = () => setExpired(true);
    window.addEventListener("session-expired", handler);
    return () => window.removeEventListener("session-expired", handler);
  }, []);
  useEffect(() => {
    setMobile(false);
    document.title = `${links.find(([path]) => location.pathname.startsWith("/admin/" + path))?.[1] || "管理中心"} · Video Mix Pro`;
  }, [location.pathname]);
  const menu = (
    <>
      <a className="brand" href="/">
        <img src="/static/brand/logo-mark.png" alt="" />
        <div>
          Video Mix Pro<small>管理中心</small>
        </div>
      </a>
      <div className="nav-caption">会员运营</div>
      <nav>
        {links.map(([path, label, number]) => (
          <NavLink key={path} to={"/admin/" + path}>
            <span className="nav-number">{number}</span>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="nav-bottom">
        <a href="/" target="_blank" rel="noreferrer">
          打开官网 ↗
        </a>
        <a href="/admin/legacy">旧版后台</a>
        <span>运营时间 · 北京时间</span>
      </div>
    </>
  );
  return (
    <div className="console">
      <aside className="sidebar">{menu}</aside>
      <Drawer
        open={mobile}
        onClose={() => setMobile(false)}
        placement="left"
        size={272}
        title="导航"
      >
        {menu}
      </Drawer>
      <div className="workspace">
        <header className="topbar">
          <div>
            <Button className="mobile-nav" onClick={() => setMobile(true)}>
              菜单
            </Button>
            <span>
              Video Mix Pro <span className="divider">/</span>{" "}
              {links.find(([path]) =>
                location.pathname.startsWith("/admin/" + path),
              )?.[1] || "管理中心"}
            </span>
          </div>
          <Button
            type="text"
            onClick={async () => {
              await fetch("/admin/logout", {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRF-Token": (await api("/session")).csrf_token },
              });
              window.location.assign("/admin/users");
            }}
          >
            退出登录
          </Button>
        </header>
        <main className="content">
          <Boundary>
            {error ? (
              <Failure message={error} retry={load} />
            ) : !ready ? (
              <Skeleton active />
            ) : (
              <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
                <Routes>
                  <Route path="users/*" element={<Users />} />
                  <Route path="codes" element={<Codes />} />
                  <Route path="batches/*" element={<Batches />} />
                  <Route path="overview" element={<Overview />} />
                  <Route path="releases" element={<Releases />} />
                  <Route path="site" element={<Site />} />
                  <Route path="audit" element={<Audit />} />
                  <Route path="*" element={<Navigate to="users" replace />} />
                </Routes>
              </Suspense>
            )}
          </Boundary>
        </main>
      </div>
      <Modal
        open={expired}
        title="登录已过期"
        closable={false}
        footer={
          <Button type="primary" onClick={() => window.location.reload()}>
            重新登录
          </Button>
        }
      >
        <p>重新登录后会回到当前页面。未发布的版本草稿已保存在本机。</p>
      </Modal>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <ConfigProvider
    button={{ autoInsertSpace: false }}
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: "#2563eb",
        colorLink: "#245dd2",
        colorLinkHover: "#1746ad",
        colorTextPlaceholder: "#637087",
        colorTextTertiary: "#637087",
        colorText: "#182238",
        colorTextSecondary: "#637087",
        colorBorder: "#e3e8f0",
        colorBgLayout: "#f4f6fa",
        borderRadius: 8,
        fontSize: 14,
        controlHeight: 40,
        fontFamily:
          'Inter, "Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
      },
      components: {
        Table: { headerBg: "#f8f9fc", cellPaddingBlock: 16 },
        Drawer: { paddingLG: 24 },
      },
    }}
  >
    <App>
      <BrowserRouter>
        <Routes>
          <Route path="/admin/*" element={<Console />} />
        </Routes>
      </BrowserRouter>
    </App>
  </ConfigProvider>,
);
