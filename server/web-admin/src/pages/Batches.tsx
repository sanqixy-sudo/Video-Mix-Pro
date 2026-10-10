import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { App, Button, Table } from "antd";
import { api, copy, date, planName, type Page } from "../api";
import {
  empty,
  Failure,
  PageTitle,
  Pager,
  Pending,
  Search,
  useQuery,
  useResource,
} from "../shared";
import { CodesTable } from "./Codes";
import CodeGenerate from "../CodeGenerate";
function Batch({ id }: { id: string }) {
  const resource = useResource("/batches/" + encodeURIComponent(id));
  const { message } = App.useApp();
  const [copying, setCopying] = useState(false);
  const b = resource.data;
  const copyBatch = async () => {
    setCopying(true);
    try {
      const codes: string[] = [];
      let page = 1,
        pages = 1;
      do {
        const result = await api<Page>(
          `/codes?batch_id=${encodeURIComponent(id)}&page_size=100&page=${page}`,
        );
        codes.push(...result.items.map((i) => i.code));
        pages = result.pages;
        page++;
      } while (page <= pages);
      await copy(codes.join("\n"));
      message.success(`已复制 ${codes.length} 个兑换码`);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCopying(false);
    }
  };
  return (
    <>
      <Link to="/admin/batches">← 返回兑换批次</Link>
      <div className="block-gap">
        <PageTitle
          title="兑换批次详情"
          description={id}
          actions={
            <>
              <Button loading={copying} onClick={copyBatch}>
                复制整个批次
              </Button>
              <Button
                type="primary"
                href={
                  "/admin/api/codes/export?scope=batch&batch_id=" +
                  encodeURIComponent(id)
                }
              >
                下载整个批次
              </Button>
            </>
          }
        />
      </div>
      <Pending
        loading={resource.loading}
        error={resource.error}
        retry={resource.reload}
      >
        {b && (
          <div className="surface block-gap">
            <div className="batch-meta">
              <div className="secondary">
                原始生成数量<b>{b.quantity}</b>
              </div>
              <div className="secondary">
                已兑换<b>{b.used}</b>
              </div>
              <div className="secondary">
                当前可用<b>{b.available}</b>
              </div>
              <div className="secondary">
                会员时长
                <b>
                  {b.plan === "custom"
                    ? `${b.custom_days} 天`
                    : planName(b.plan)}
                </b>
              </div>
            </div>
            <div className="section-body">
              <p>
                生成于 {date(b.created_at)} · 兑换截止：
                {b.expires_at ? date(b.expires_at) : "不限"}
              </p>
              <p className="wrap">{b.note || "本批次无备注"}</p>
            </div>
          </div>
        )}
      </Pending>
      <div className="block-gap">
        <CodesTable batchId={id} />
      </div>
    </>
  );
}
function BatchList() {
  const { params, query, update } = useQuery();
  const resource = useResource<Page>("/batches?" + query);
  const [generate, setGenerate] = useState(false);
  return (
    <>
      <PageTitle
        title="兑换批次"
        description="每次生成都有独立记录，随时找回发码结果与兑换进度。"
        actions={
          <Button type="primary" onClick={() => setGenerate(true)}>
            生成兑换码
          </Button>
        }
      />
      <div className="surface">
        <div className="filterbar">
          <Search
            placeholder="搜索批次编号或备注"
            value={params.get("q") || ""}
            onChange={(q) => update({ q })}
          />
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
            columns={[
              {
                title: "批次",
                dataIndex: "id",
                render: (v: string, r) => (
                  <>
                    <Link className="wrap" to={"/admin/batches/" + v}>
                      {v}
                    </Link>
                    <span className="subline">{r.note || "无备注"}</span>
                  </>
                ),
              },
              {
                title: "会员时长",
                dataIndex: "plan",
                render: (v: string, r) =>
                  v === "custom" ? `${r.custom_days} 天` : planName(v),
              },
              {
                title: "生成 / 可用 / 已兑",
                key: "counts",
                render: (_, r) => `${r.quantity} / ${r.available} / ${r.used}`,
              },
              { title: "生成时间", dataIndex: "created_at", render: date },
            ]}
          />
        )}
        <Pager data={resource.data} update={update} />
      </div>
      {generate && <CodeGenerate onClose={() => setGenerate(false)} />}
    </>
  );
}
export default function Batches() {
  const id = useLocation().pathname.split("/")[3];
  return id ? <Batch key={id} id={decodeURIComponent(id)} /> : <BatchList />;
}
