import { Link } from "react-router-dom";
import { Button, Table } from "antd";
import { date, type Page } from "../api";
import { empty, PageTitle, Pending, useResource } from "../shared";
export default function Overview() {
  const summary = useResource("/summary");
  const recent = useResource<Page>("/audit?page_size=10");
  const cards = [
    ["有效会员", "members_active", "users?status=active", "查看有效会员"],
    [
      "7 天内到期",
      "members_expiring_7d",
      "users?status=expiring",
      "处理近期续费",
    ],
    [
      "设备冷却",
      "devices_cooling_down",
      "users?device=cooldown",
      "查看设备问题",
    ],
    ["可用兑换码", "codes_available", "codes?status=available", "查看可发放码"],
  ];
  return (
    <>
      <PageTitle
        title="工作台"
        description="掌握会员状态，继续今天的运营工作。所有日期按北京时间统计。"
        actions={
          <Button
            onClick={() => {
              summary.reload();
              recent.reload();
            }}
          >
            刷新
          </Button>
        }
      />
      <Pending
        loading={summary.loading}
        error={summary.error}
        retry={summary.reload}
      >
        <div className="metrics">
          {cards.map(([title, key, url, caption]) => (
            <Link className="metric" to={"/admin/" + url} key={key}>
              {title}
              <b>{summary.data?.metrics[key] ?? 0}</b>
              <span className="secondary">{caption} →</span>
            </Link>
          ))}
        </div>
        <p className="secondary">
          用户总数 {summary.data?.metrics.users_total} · 今日注册{" "}
          {summary.data?.metrics.registrations_today} · 今日兑换{" "}
          {summary.data?.metrics.redeemed_today}
        </p>
      </Pending>
      <section className="surface block-gap">
        <div className="section-head">
          <h2>最近操作</h2>
          <Link to="/admin/audit">全部记录 →</Link>
        </div>
        <Pending
          loading={recent.loading}
          error={recent.error}
          retry={recent.reload}
        >
          <Table
            ref={(table) => {
              if (table) table.nativeElement.tabIndex = 0;
            }}
            rowKey="id"
            pagination={false}
            dataSource={recent.data?.items || []}
            locale={{ emptyText: empty }}
            columns={[
              { title: "时间", dataIndex: "created_at", render: date },
              { title: "操作", dataIndex: "action" },
              {
                title: "对象",
                dataIndex: "target",
                render: (v) => <span className="wrap">{v || "—"}</span>,
              },
              { title: "操作者", dataIndex: "actor" },
            ]}
          />
        </Pending>
      </section>
    </>
  );
}
