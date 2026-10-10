import { Table } from "antd";
import { date, type Page, type Row } from "../api";
import {
  AuditDetail,
  DateFilter,
  empty,
  Failure,
  Filter,
  PageTitle,
  Pager,
  Search,
  useQuery,
  useResource,
} from "../shared";
export default function Audit() {
  const { params, query, update } = useQuery();
  const resource = useResource<Page & { actions: string[] }>("/audit?" + query);
  return (
    <>
      <PageTitle
        title="操作记录"
        description="按用户、动作和时间追溯变更，展开记录查看前后值。"
      />
      <section className="surface">
        <div className="filterbar">
          <Search
            value={params.get("q") || ""}
            onChange={(q) => update({ q })}
            placeholder="搜索用户、对象或操作内容"
          />
          <Filter
            label="操作类型"
            value={params.get("action") || ""}
            onChange={(action) => update({ action })}
            options={
              resource.data?.actions.map((action) => ({
                value: action,
                label: action,
              })) || []
            }
          />
          <DateFilter label="操作日期" params={params} update={update} />
        </div>
        {resource.error ? (
          <Failure message={resource.error} retry={resource.reload} />
        ) : (
          <Table
            ref={(table) => {
              if (table) table.nativeElement.tabIndex = 0;
            }}
            rowKey="id"
            pagination={false}
            loading={resource.loading}
            dataSource={resource.data?.items || []}
            locale={{ emptyText: empty }}
            expandable={{
              expandedRowRender: (r: Row) => <AuditDetail value={r.detail} />,
            }}
            columns={[
              { title: "时间", dataIndex: "created_at", render: date },
              { title: "操作", dataIndex: "action" },
              {
                title: "对象",
                dataIndex: "target",
                render: (v) => <span className="wrap">{v || "—"}</span>,
              },
              { title: "操作者", dataIndex: "actor" },
              { title: "IP", dataIndex: "ip", responsive: ["lg"] },
            ]}
          />
        )}
        <Pager data={resource.data} update={update} />
      </section>
    </>
  );
}
