import { useEffect, useState } from "react";
import { Alert, App, Button, Form, Input } from "antd";
import { api } from "../api";
import { PageTitle, Pending, useResource } from "../shared";
export default function Site() {
  const resource = useResource("/site");
  const [form] = Form.useForm();
  const [pricing] = Form.useForm();
  const [saving, setSaving] = useState("");
  const { message } = App.useApp();
  useEffect(() => {
    if (resource.data) {
      form.setFieldsValue(resource.data.settings);
      pricing.setFieldsValue(
        Object.fromEntries(
          resource.data.pricing.map(
            (p: { plan: string; price_display: string }) => [
              p.plan,
              p.price_display,
            ],
          ),
        ),
      );
    }
  }, [resource.data, form, pricing]);
  const save = async (kind: string) => {
    try {
      const values = await (kind === "site" ? form : pricing).validateFields();
      setSaving(kind);
      await api("/" + kind, kind === "site" ? values : { prices: values });
      message.success(kind === "site" ? "官网内容已保存" : "套餐价格已保存");
    } catch (e) {
      if (e instanceof Error) message.error(e.message);
    } finally {
      setSaving("");
    }
  };
  return (
    <div className="site-settings">
      <PageTitle
        title="官网设置"
        description="维护套餐、联系开通方式和下载帮助。未配置的入口会自动隐藏。"
        actions={
          <Button href="/" target="_blank">
            预览官网 ↗
          </Button>
        }
      />
      <Pending
        loading={resource.loading}
        error={resource.error}
        retry={resource.reload}
      >
        <section className="surface section-body">
          <h2>联系开通与帮助</h2>
          <Alert
            type="info"
            title="首期通过联系开通会员"
            description="填写实际可用的联系方式。官网套餐按钮会带上所选套餐，不会跳转到在线支付。"
          />
          <Form form={form} layout="vertical">
            <div className="form-grid">
              <Form.Item label="联系方式名称" name="contact_label">
                <Input maxLength={80} placeholder="例如：微信" />
              </Form.Item>
              <Form.Item label="联系账号" name="contact_value">
                <Input maxLength={200} placeholder="填写实际联系账号" />
              </Form.Item>
              <Form.Item
                className="full"
                label="联系链接（选填）"
                name="contact_url"
                rules={[
                  { type: "url", message: "请填写有效的 HTTPS 地址" },
                  { pattern: /^https:\/\//, message: "仅支持 HTTPS 地址" },
                ]}
              >
                <Input placeholder="https://" />
              </Form.Item>
              <Form.Item
                className="full"
                label="下载与安装说明"
                name="download_notes"
              >
                <Input.TextArea
                  rows={4}
                  maxLength={4000}
                  showCount
                  placeholder="安装版、便携版的适用场景及安装说明"
                />
              </Form.Item>
              <Form.Item
                className="full"
                label="帮助与售后说明"
                name="help_text"
              >
                <Input.TextArea rows={4} maxLength={4000} showCount />
              </Form.Item>
            </div>
            <Button
              type="primary"
              loading={saving === "site"}
              onClick={() => save("site")}
            >
              保存官网内容
            </Button>
          </Form>
        </section>
        <section className="surface section-body block-gap">
          <h2>套餐价格</h2>
          <p className="helper">
            保留现有套餐时长。价格留空时显示「联系咨询」，实际开通以沟通确认为准。
          </p>
          <Form form={pricing} layout="vertical">
            <div className="form-grid">
              {resource.data?.pricing.map(
                (p: { plan: string; label: string }) => (
                  <Form.Item
                    key={p.plan}
                    name={p.plan}
                    label={p.label + "会员"}
                  >
                    <Input maxLength={40} placeholder="例如：¥ 99" />
                  </Form.Item>
                ),
              )}
            </div>
            <Button
              type="primary"
              loading={saving === "pricing"}
              onClick={() => save("pricing")}
            >
              保存套餐价格
            </Button>
          </Form>
        </section>
      </Pending>
    </div>
  );
}
