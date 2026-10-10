import { useState } from "react";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Form,
  InputNumber,
  Modal,
  Select,
  Space,
} from "antd";
import {
  api,
  ApiError,
  date,
  operationId,
  plans,
  planName,
  type Row,
} from "./api";
import { dayjs } from "./shared";
export const actions: Record<string, { label: string; description: string }> = {
  grant: {
    label: "续费 / 开通会员",
    description:
      "有效会员从原到期时间累计；已到期会员从现在累计。永久会员会跳过，封禁账号续费后仍保持封禁。",
  },
  adjust_expiry: {
    label: "调整到期日",
    description:
      "直接设置到期时间，不按剩余时长累计。永久会员也会转为定期会员，请核对预览。",
  },
  revoke: {
    label: "撤销会员",
    description: "清除会员资格并退出该账号当前客户端会话。保留账号及历史记录。",
  },
  ban: {
    label: "封禁账号",
    description:
      "账号将无法登录或兑换，现有客户端会话退出。会员到期时间保持不变。",
  },
  unban: {
    label: "解除封禁",
    description: "恢复账号登录资格；会员是否有效仍由到期时间决定。",
  },
  reset_device: {
    label: "解绑设备",
    description: "清空设备与换绑冷却并退出客户端会话。下次登录会绑定新设备。",
  },
  reset_device_cooldown: {
    label: "解除设备冷却",
    description: "立即允许下一次换绑；不会改变当前绑定设备。",
  },
};
export default function MembershipDialog({
  ids,
  action,
  onClose,
  onDone,
}: {
  ids: number[];
  action: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form] = Form.useForm();
  const [preview, setPreview] = useState<Row>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [request, setRequest] = useState<Row>();
  const { message } = App.useApp();
  const plan = Form.useWatch("plan", form);
  const meta = actions[action];
  const prepare = async () => {
    try {
      const values = await form.validateFields();
      setBusy(true);
      setError("");
      const data = request || {
        operation_id: operationId(),
        user_ids: ids,
        action,
        ...values,
        expires_at: values.expires_at?.toISOString(),
      };
      setRequest(data);
      setPreview(await api("/membership/preview", data));
    } catch (e) {
      if (e instanceof ApiError && [400, 422].includes(e.status))
        setRequest(undefined);
      if (e instanceof Error) setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api("/membership/commit", {
        operation_id: preview.operation_id,
      });
      setPreview(result);
      onDone();
      message.success(`已完成 ${result.affected} 项操作`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setPreview(undefined);
        setRequest(undefined);
      }
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const completed = preview?.status === "completed";
  return (
    <Modal
      open
      title={`${meta.label} · ${ids.length} 位用户`}
      width={720}
      onCancel={() => !busy && onClose()}
      maskClosable={!busy}
      closable={!busy}
      footer={
        <Space>
          <Button onClick={onClose} disabled={busy}>
            {completed ? "关闭" : "取消"}
          </Button>
          {!completed &&
            (preview ? (
              <>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setPreview(undefined);
                    setRequest(undefined);
                  }}
                >
                  返回修改
                </Button>
                <Button
                  danger={["revoke", "ban", "adjust_expiry"].includes(action)}
                  type="primary"
                  loading={busy}
                  onClick={commit}
                >
                  确认执行
                </Button>
              </>
            ) : (
              <Button type="primary" loading={busy} onClick={prepare}>
                {request ? "重试原预览" : "预览变更"}
              </Button>
            ))}
        </Space>
      }
    >
      <p>{meta.description}</p>
      {error && <Alert type="error" title={error} showIcon />}
      {!preview && (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ plan: "month", custom_days: 31 }}
          disabled={busy || !!request}
        >
          {action === "grant" && (
            <div className="form-grid">
              <Form.Item
                name="plan"
                label="增加会员时长"
                rules={[{ required: true }]}
              >
                <Select options={plans} />
              </Form.Item>
              {plan === "custom" && (
                <Form.Item
                  name="custom_days"
                  label="增加天数"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={1} max={36500} precision={0} />
                </Form.Item>
              )}
            </div>
          )}
          {action === "adjust_expiry" && (
            <Form.Item
              label="新的到期日期（北京时间，当天结束）"
              name="expires_at"
              rules={[{ required: true }]}
              getValueFromEvent={(v) =>
                v
                  ? dayjs
                      .tz(v.format("YYYY-MM-DD"), "Asia/Shanghai")
                      .endOf("day")
                  : null
              }
            >
              <DatePicker style={{ width: "100%" }} />
            </Form.Item>
          )}
        </Form>
      )}
      {preview && (
        <div className="operation-result">
          {preview.items.map((item: Row) => (
            <article key={item.id}>
              <strong>{item.username || `用户 #${item.id}`}</strong>
              <span className="subline">
                {item.status === "success"
                  ? "已完成"
                  : item.status === "skipped"
                    ? `跳过 · ${item.reason}`
                    : "待确认"}
              </span>
              {item.before && action === "grant" && (
                <div className="change-line">
                  <div>
                    当前到期
                    <br />
                    {date(item.before.member_expires_at)}
                  </div>
                  <span className="arrow">→</span>
                  <div>
                    变更后
                    <br />
                    <strong>
                      {item.after.plan === "permanent"
                        ? "永久会员"
                        : date(item.after.member_expires_at)}
                    </strong>
                    <span className="subline">{planName(item.after.plan)}</span>
                  </div>
                </div>
              )}
              {item.before && action === "adjust_expiry" && (
                <p>
                  {date(item.before.member_expires_at)} →{" "}
                  <b>{date(item.after.member_expires_at)}</b>
                </p>
              )}
              {item.warning && (
                <div className="operation-note">{item.warning}</div>
              )}
            </article>
          ))}
        </div>
      )}
      {preview && !completed && (
        <p className="helper">
          预览保留 30 分钟。期间发生兑换、会员或账号变更时，会要求重新预览。
        </p>
      )}
    </Modal>
  );
}
