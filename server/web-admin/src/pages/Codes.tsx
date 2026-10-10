import { useState } from "react";
import { Link } from "react-router-dom";
import { App, Button, Dropdown, Modal, Select, Space, Table } from "antd";
import {
  api,
  copy,
  date,
  operationId,
  planName,
  type Page,
  type Row,
} from "../api";
import {
  CodeStatus,
  DateFilter,
  empty,
  Failure,
  Filter,
  PageTitle,
  Pager,
  Search,
  useQuery,
  useResource,
  useSelection,
} from "../shared";
import CodeGenerate, { hasPendingGeneration } from "../CodeGenerate";
export function CodesTable({ batchId }: { batchId?: string }) {
  const { params, query, update } = useQuery();
  const p = new URLSearchParams(query);
  if (batchId) p.set("batch_id", batchId);
  const resource = useResource<Page>("/codes?" + p);
  const selection = useSelection(query, 500);
  const { message } = App.useApp();
  const [result, setResult] = useState<Row>();
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Row>();
  const [error, setError] = useState("");
  const requestAction = (action: string) => {
    setError("");
    setResult(undefined);
    setPending({ operation_id: operationId(), action, codes: selection.keys });
  };
  const execute = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await api("/code_action", pending));
      setPending(undefined);
      resource.reload();
      selection.clear();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const exportTo = (scope: string) => {
    const next = new URLSearchParams(p);
    next.set("scope", scope);
    if (scope === "selected") next.set("codes", selection.keys.join(","));
    window.location.assign("/admin/api/codes/export?" + next);
  };
  return (
    <>
      {!!selection.keys.length && (
        <div className="selection-bar">
          <span>
            已选 <strong>{selection.keys.length}</strong> 个兑换码
          </span>
          <Space wrap>
            <Button
              onClick={() =>
                copy(selection.keys.join("\n"))
                  .then(() => message.success("所选兑换码已复制"))
                  .catch(() => message.error("复制失败，请使用导出"))
              }
            >
              复制所选
            </Button>
            <Button onClick={() => requestAction("disable")}>停用所选</Button>
            <Button onClick={() => requestAction("enable")}>恢复所选</Button>
            <Button type="text" onClick={selection.clear}>
              清空选择
            </Button>
          </Space>
        </div>
      )}
      <div className="surface">
        <div className="filterbar">
          <Search
            value={params.get("q") || ""}
            onChange={(q) => update({ q })}
            placeholder="搜索兑换码、兑换账号或备注"
          />
          <Filter
            label="兑换状态"
            value={params.get("status") || ""}
            onChange={(status) => update({ status })}
            options={[
              { value: "available", label: "可用" },
              { value: "used", label: "已使用" },
              { value: "disabled", label: "已停用" },
              { value: "expired", label: "已过期" },
            ]}
          />
          {!batchId && (
            <Search
              value={params.get("batch_id") || ""}
              onChange={(batch_id) => update({ batch_id })}
              placeholder="按批次编号筛选"
            />
          )}
          <Select
            aria-label="排序"
            value={params.get("sort") || "created_desc"}
            onChange={(sort) => update({ sort })}
            options={[
              { value: "created_desc", label: "最新生成优先" },
              { value: "created_asc", label: "最早生成优先" },
            ]}
          />
          <DateFilter params={params} update={update} />
          <Dropdown
            menu={{
              items: [
                {
                  key: "filtered",
                  label: `导出当前筛选（${resource.data?.total ?? "…"} 条）`,
                },
                {
                  key: "selected",
                  label: `导出已选兑换码（${selection.keys.length} 条）`,
                  disabled: !selection.keys.length,
                },
                ...(batchId ? [{ key: "batch", label: "导出整个批次" }] : []),
              ],
              onClick: ({ key }) => exportTo(key),
            }}
          >
            <Button>导出 CSV</Button>
          </Dropdown>
        </div>
        {resource.error ? (
          <div className="section-body">
            <Failure message={resource.error} retry={resource.reload} />
          </div>
        ) : (
          <Table
            ref={(table) => {
              if (table) table.nativeElement.tabIndex = 0;
            }}
            rowKey="code"
            loading={resource.loading}
            dataSource={resource.data?.items || []}
            rowSelection={selection.selection}
            pagination={false}
            locale={{ emptyText: empty }}
            columns={[
              {
                title: "兑换码",
                dataIndex: "code",
                width: 250,
                render: (v: string, r: Row) => (
                  <>
                    <button
                      className="code-copy ant-btn ant-btn-link"
                      onClick={() =>
                        copy(v)
                          .then(() => message.success("兑换码已复制"))
                          .catch(() => message.error("复制失败，请使用导出"))
                      }
                    >
                      <span className="copyable">{v}</span>
                    </button>
                    <span className="subline">{r.note || "无备注"}</span>
                  </>
                ),
              },
              {
                title: "状态",
                dataIndex: "status",
                width: 100,
                render: (v: string) => <CodeStatus status={v} />,
              },
              {
                title: "会员时长",
                dataIndex: "plan",
                width: 130,
                render: (v: string, r: Row) =>
                  v === "custom" ? `${r.custom_days} 天` : planName(v),
              },
              {
                title: "兑换截止",
                dataIndex: "expires_at",
                width: 165,
                render: (v: string) => (v ? date(v) : "不限"),
              },
              {
                title: "兑换记录",
                dataIndex: "used_by_username_snapshot",
                width: 180,
                render: (v: string, r: Row) =>
                  v ? (
                    <>
                      <Link to={"/admin/users/" + r.used_by}>{v}</Link>
                      <span className="subline">{date(r.used_at)}</span>
                    </>
                  ) : (
                    "—"
                  ),
              },
              ...(!batchId
                ? [
                    {
                      title: "批次",
                      dataIndex: "batch_id",
                      width: 180,
                      render: (v: string) => (
                        <Link className="wrap" to={"/admin/batches/" + v}>
                          {v}
                        </Link>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        )}
        <Pager data={resource.data} update={update} />
      </div>
      <Modal
        open={!!pending || !!result}
        title={
          result
            ? "兑换码操作结果"
            : pending?.action === "disable"
              ? "停用所选兑换码"
              : "恢复所选兑换码"
        }
        onCancel={() => !busy && (setPending(undefined), setResult(undefined))}
        footer={
          result ? (
            <Button onClick={() => setResult(undefined)}>关闭</Button>
          ) : (
            <Space>
              <Button disabled={busy} onClick={() => setPending(undefined)}>
                取消
              </Button>
              <Button type="primary" loading={busy} onClick={execute}>
                {error ? "重试原操作" : "确认执行"}
              </Button>
            </Space>
          )
        }
      >
        <p>
          每次最多处理 500
          个。已使用和已过期的码会跳过；恢复不会使它们重新可兑换。
        </p>
        {error && <Failure message={error} retry={execute} />}{" "}
        {result && (
          <>
            <p>
              成功 {result.affected}，跳过{" "}
              {result.items.filter((i: Row) => i.status === "skipped").length}
              ，失败{" "}
              {result.items.filter((i: Row) => i.status === "failed").length}。
            </p>
            <div className="operation-result">
              {result.items.map((i: Row) => (
                <p key={i.code} className="copyable">
                  {i.code} · {i.status === "success" ? "成功" : i.reason}
                </p>
              ))}
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
export default function Codes() {
  const [generate, setGenerate] = useState(false);
  return (
    <>
      <PageTitle
        title="兑换码"
        description="生成、交付和追踪会员兑换码，按明确范围复制与导出。"
        actions={
          <Button type="primary" onClick={() => setGenerate(true)}>
            {hasPendingGeneration() ? "恢复生成请求" : "生成兑换码"}
          </Button>
        }
      />
      <CodesTable />
      {generate && <CodeGenerate onClose={() => setGenerate(false)} />}
    </>
  );
}
