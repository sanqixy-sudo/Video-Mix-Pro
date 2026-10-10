import { useState } from "react";
import {
  Alert,
  Button,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
} from "antd";
import { useNavigate } from "react-router-dom";
import { api, ApiError, operationId, plans, type Row } from "./api";
import { dayjs } from "./shared";
const pendingKey = "vmp.pending-code-generation";
export function hasPendingGeneration() {
  return !!localStorage.getItem(pendingKey);
}
export default function CodeGenerate({ onClose }: { onClose: () => void }) {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<Row | undefined>(() => {
    try {
      return (
        JSON.parse(localStorage.getItem(pendingKey) || "null") || undefined
      );
    } catch {
      return undefined;
    }
  });
  const plan = Form.useWatch("plan", form);
  const submit = async () => {
    try {
      const values = pending || (await form.validateFields());
      setBusy(true);
      setError("");
      const data = pending || {
        ...values,
        operation_id: operationId(),
        expires_at: values.expires_at?.toISOString(),
      };
      setPending(data);
      localStorage.setItem(pendingKey, JSON.stringify(data));
      const result = await api("/create_codes", data);
      localStorage.removeItem(pendingKey);
      navigate("/admin/batches/" + result.batch_id);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && [400, 422].includes(e.status)) {
        localStorage.removeItem(pendingKey);
        setPending(undefined);
      }
      if (e instanceof Error) setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const find = async () => {
    if (!pending) return;
    setBusy(true);
    setError("");
    try {
      const result = await api("/operations/" + pending.operation_id);
      if (result.status === "completed") {
        localStorage.removeItem(pendingKey);
        navigate("/admin/batches/" + result.batch_id);
        onClose();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title="生成兑换码"
      width={640}
      onCancel={() => !busy && onClose()}
      closable={!busy}
      maskClosable={!busy}
      footer={
        <Space>
          <Button onClick={onClose} disabled={busy}>
            关闭
          </Button>
          {pending && (
            <Button onClick={find} disabled={busy}>
              查询原结果
            </Button>
          )}
          <Button type="primary" onClick={submit} loading={busy}>
            {pending ? "重试原生成请求" : "生成并查看批次"}
          </Button>
        </Space>
      }
    >
      <p>会员时长从用户兑换时计算；兑换截止时间决定该码何时不能再兑换。</p>
      {error && <Alert type="error" showIcon title={error} />}{" "}
      {pending && (
        <Alert
          type="info"
          title="生成请求已保留"
          description={`批次数量 ${pending.count}。查询结果或重试会使用同一操作编号，不会创建第二批。`}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ plan: "month", count: 100, custom_days: 31 }}
        disabled={busy || !!pending}
      >
        <div className="form-grid">
          <Form.Item
            name="plan"
            label="兑换后获得的会员"
            rules={[{ required: true }]}
          >
            <Select options={plans} />
          </Form.Item>
          <Form.Item name="count" label="生成数量" rules={[{ required: true }]}>
            <InputNumber min={1} max={500} precision={0} />
          </Form.Item>
          {plan === "custom" && (
            <Form.Item
              name="custom_days"
              label="兑换后会员天数"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={36500} precision={0} />
            </Form.Item>
          )}
          <Form.Item
            className="full"
            name="expires_at"
            label="兑换截止日期（选填，北京时间当天结束）"
            getValueFromEvent={(v) =>
              v
                ? dayjs.tz(v.format("YYYY-MM-DD"), "Asia/Shanghai").endOf("day")
                : null
            }
          >
            <DatePicker
              disabledDate={(v) =>
                v.isBefore(dayjs().tz("Asia/Shanghai").startOf("day"))
              }
            />
          </Form.Item>
          <Form.Item className="full" name="note" label="批次备注">
            <Input.TextArea
              maxLength={1000}
              showCount
              placeholder="例如：10 月客户续费交付"
              rows={3}
            />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
