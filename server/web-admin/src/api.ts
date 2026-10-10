export type Row = Record<string, any>;
export type Page<T = Row> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};
let csrf =
  document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content ||
  "";
export function setCsrf(value: string) {
  csrf = value;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public payload: Row,
  ) {
    super(
      typeof payload.detail === "string"
        ? payload.detail
        : payload.message || payload.detail?.message || `请求失败（${status}）`,
    );
  }
}
export async function api<T = Row>(
  path: string,
  data?: unknown,
  signal?: AbortSignal,
  method?: string,
): Promise<T> {
  const timeout = AbortSignal.timeout(20000);
  const response = await fetch("/admin/api" + path, {
    credentials: "same-origin",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    method: method || (data === undefined ? "GET" : "POST"),
    headers:
      data === undefined
        ? {}
        : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: data === undefined ? undefined : JSON.stringify(data),
  }).catch((error: Error) => {
    if (error.name === "TimeoutError")
      throw new Error(
        "请求超时。原操作可以安全重试；兑换码也可查询原批次结果。",
      );
    if (error instanceof TypeError)
      throw new Error("网络连接失败，请检查连接后重试。");
    throw error;
  });
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, payload);
  }
  return payload as T;
}
export function operationId() {
  return crypto.randomUUID();
}
export const plans = [
  { value: "month", label: "月会员 · 31 天" },
  { value: "quarter", label: "季会员 · 93 天" },
  { value: "half_year", label: "半年会员 · 186 天" },
  { value: "year", label: "一年会员 · 366 天" },
  { value: "permanent", label: "永久会员" },
  { value: "custom", label: "自定义天数" },
];
export const planName = (value: string) =>
  plans.find((p) => p.value === value)?.label.split(" · ")[0] ||
  value ||
  "未开通";
export function date(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(value))
    : "—";
}
export async function copy(text: string) {
  await navigator.clipboard.writeText(text);
}
