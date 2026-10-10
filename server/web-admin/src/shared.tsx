import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Empty,
  Input,
  Pagination,
  Select,
  Skeleton,
  Space,
  Tag,
} from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { api, date, type Page, type Row } from "./api";
dayjs.extend(utc);
dayjs.extend(timezone);
export function useQuery() {
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const update = useCallback(
    (values: Record<string, string | number | undefined>) =>
      setParams((old) => {
        const next = new URLSearchParams(old);
        if (!("page" in values)) next.delete("page");
        Object.entries(values).forEach(([key, value]) =>
          value === undefined || value === ""
            ? next.delete(key)
            : next.set(key, String(value)),
        );
        return next;
      }),
    [setParams],
  );
  return { params, query, update };
}
export function useResource<T = Row>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    api<T>(path, undefined, controller.signal)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => {
        if (active && e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [path, revision]);
  return {
    data,
    error,
    loading,
    reload: useCallback(() => setRevision((x) => x + 1), []),
  };
}
export function Failure({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <Alert
      type="error"
      showIcon
      title="暂时无法加载"
      description={message}
      action={<Button onClick={retry}>重试</Button>}
    />
  );
}
export function PageTitle({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="heading-actions">{actions}</div>
    </div>
  );
}
export function Search({
  value,
  onChange,
  placeholder = "搜索",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  const callback = useRef(onChange);
  callback.current = onChange;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    setText(value);
  }, [value]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <Input
      allowClear
      value={text}
      placeholder={placeholder}
      aria-label={placeholder}
      onChange={(e) => {
        const next = e.target.value;
        setText(next);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => callback.current(next), 320);
      }}
    />
  );
}
export function Filter({
  value,
  onChange,
  label,
  options,
}: {
  value?: string;
  onChange: (v: string) => void;
  label: string;
  options: { value: string; label: string }[];
}) {
  return (
    <Select
      aria-label={label}
      placeholder={label}
      allowClear
      value={value || undefined}
      onChange={(v) => onChange(v || "")}
      options={options}
    />
  );
}
export function DateFilter({
  params,
  update,
  prefix = "created",
  label = "创建日期",
}: {
  params: URLSearchParams;
  update: (v: Record<string, string>) => void;
  prefix?: string;
  label?: string;
}) {
  return (
    <DatePicker.RangePicker
      aria-label={label}
      placeholder={[label + "起", label + "止"]}
      value={
        params.get(prefix + "_from") && params.get(prefix + "_to")
          ? [
              dayjs(params.get(prefix + "_from")).tz("Asia/Shanghai"),
              dayjs(params.get(prefix + "_to")).tz("Asia/Shanghai"),
            ]
          : null
      }
      onChange={(v) =>
        update({
          [prefix + "_from"]: v?.[0]
            ? dayjs
                .tz(v[0].format("YYYY-MM-DD"), "Asia/Shanghai")
                .startOf("day")
                .toISOString()
            : "",
          [prefix + "_to"]: v?.[1]
            ? dayjs
                .tz(v[1].format("YYYY-MM-DD"), "Asia/Shanghai")
                .endOf("day")
                .toISOString()
            : "",
        })
      }
    />
  );
}
export function Pager({
  data,
  update,
}: {
  data?: Page;
  update: (v: Record<string, number>) => void;
}) {
  return data ? (
    <div className="pagination">
      <span className="secondary">
        {data.total
          ? `${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total)}`
          : "0"}{" "}
        条，共 {data.total} 条
      </span>
      <Pagination
        current={data.page}
        pageSize={data.page_size}
        total={data.total}
        showSizeChanger
        showQuickJumper
        pageSizeOptions={[25, 50, 100]}
        onChange={(page, page_size) =>
          update({ page: page_size !== data.page_size ? 1 : page, page_size })
        }
      />
    </div>
  ) : null;
}
export function useSelection(query: string, limit: number) {
  const [keys, setKeys] = useState<React.Key[]>([]);
  const { message } = App.useApp();
  const signature = new URLSearchParams(query);
  signature.delete("page");
  signature.delete("page_size");
  const identity = signature.toString();
  const prior = useRef(identity);
  useEffect(() => {
    if (prior.current !== identity) {
      setKeys((old) => {
        if (old.length) message.info("查询或排序已改变，已清空所选记录");
        return [];
      });
      prior.current = identity;
    }
  }, [identity, message]);
  return {
    keys,
    clear: () => setKeys([]),
    selection: {
      selectedRowKeys: keys,
      preserveSelectedRowKeys: true,
      columnWidth: 72,
      columnTitle: (checkbox: React.ReactNode) => (
        <span title="全选本页">
          {checkbox}
          <span className="secondary" style={{ marginLeft: 6 }}>
            本页
          </span>
        </span>
      ),
      onChange: (next: React.Key[]) => {
        if (next.length > limit) message.warning(`每次最多选择 ${limit} 条`);
        else setKeys(next);
      },
    },
  };
}
const memberLabels: Record<string, string> = {
  active: "有效会员",
  permanent: "永久会员",
  expired: "会员已到期",
  none: "未开通",
};
export function MemberStatus({ user }: { user: Row }) {
  return (
    <Space size={4} wrap>
      <Tag
        color={
          ["active", "permanent"].includes(user.membership_status)
            ? "blue"
            : undefined
        }
      >
        {memberLabels[user.membership_status] || "未开通"}
      </Tag>
      {!!user.is_banned && <Tag color="red">账号封禁</Tag>}
    </Space>
  );
}
export function CodeStatus({ status }: { status: string }) {
  return (
    <Tag
      color={
        {
          available: "green",
          used: "blue",
          disabled: "default",
          expired: "orange",
        }[status]
      }
    >
      {(
        {
          available: "可用",
          used: "已使用",
          disabled: "已停用",
          expired: "已过期",
        } as Row
      )[status] || status}
    </Tag>
  );
}
export function Countdown({ until }: { until?: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!until) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [until]);
  const remaining = until
    ? Math.max(0, Math.ceil((new Date(until).getTime() - now) / 1000))
    : 0;
  return (
    <span className="secondary">
      {remaining
        ? `冷却 ${Math.floor(remaining / 3600)}:${String(Math.floor((remaining % 3600) / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`
        : "可换绑"}
    </span>
  );
}
export function Pending({
  loading,
  error,
  retry,
  children,
}: {
  loading: boolean;
  error: string;
  retry: () => void;
  children: React.ReactNode;
}) {
  if (error) return <Failure message={error} retry={retry} />;
  return loading ? (
    <Skeleton active paragraph={{ rows: 5 }} />
  ) : (
    <>{children}</>
  );
}
export const empty = (
  <Empty
    image={Empty.PRESENTED_IMAGE_SIMPLE}
    description="暂无符合条件的记录"
  />
);
export function AuditDetail({ value }: { value: string }) {
  try {
    const obj = JSON.parse(value);
    if (obj.before && obj.after)
      return (
        <div className="change-values">
          {Object.keys(obj.after).map((k) => (
            <div key={k}>
              <b>
                {(
                  {
                    is_member: "会员",
                    plan: "套餐",
                    member_expires_at: "到期时间",
                    is_banned: "封禁",
                    device_id: "设备",
                    device_rebind_cooldown_until: "冷却截止",
                    note: "备注",
                  } as Row
                )[k] || k}
              </b>
              <span>
                {String(obj.before[k] ?? "—")} → {String(obj.after[k] ?? "—")}
              </span>
            </div>
          ))}
        </div>
      );
  } catch {}
  return <span className="wrap">{value || "—"}</span>;
}
export { dayjs, date };
