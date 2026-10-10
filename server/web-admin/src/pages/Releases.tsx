import { useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import { api, date, type Row } from "../api";
import {
  empty,
  Failure,
  PageTitle,
  Pager,
  useQuery,
  useResource,
} from "../shared";
const draftKey = "vmp.release-draft.v1";
function Fields() {
  return (
    <>
      <div className="form-grid">
        <Form.Item
          name="latest_version"
          label="发布版本"
          rules={[
            {
              required: true,
              pattern: /^\d+\.\d+\.\d+$/,
              message: "例如 0.3.0",
            },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="minimum_version"
          label="最低支持版本"
          rules={[{ required: true, pattern: /^\d+\.\d+\.\d+$/ }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="title"
          className="full"
          label="更新标题"
          rules={[{ required: true }]}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="notes" className="full" label="更新内容">
          <Input.TextArea rows={7} maxLength={10000} />
        </Form.Item>
        <Form.Item
          name="download_url"
          className="full"
          label="安装版下载地址"
          extra="HTTPS GitHub Releases 文件直链"
        >
          <Input placeholder="https://github.com/…/releases/download/…/setup.exe" />
        </Form.Item>
        <Form.Item
          name="sha256"
          className="full"
          label="安装版 SHA-256"
          rules={[
            {
              pattern: /^[a-fA-F0-9]{64}$/,
              message: "请输入 64 位十六进制校验值",
            },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item name="portable_url" className="full" label="便携版下载地址">
          <Input placeholder="https://github.com/…/releases/download/…/portable.zip" />
        </Form.Item>
        <Form.Item
          name="portable_sha256"
          className="full"
          label="便携版 SHA-256"
          rules={[
            {
              pattern: /^[a-fA-F0-9]{64}$/,
              message: "请输入 64 位十六进制校验值",
            },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="is_mandatory"
          label="强制所有旧版本更新"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
      </div>
      <p className="helper">
        低于最低支持版本的客户端必须更新。下载地址未填写时官网隐藏对应下载入口。
      </p>
    </>
  );
}
export default function Releases() {
  const { query, update } = useQuery();
  const resource = useResource("/releases?" + query);
  const [form] = Form.useForm();
  const [historyForm] = Form.useForm();
  const initialized = useRef(false);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [edit, setEdit] = useState<Row>();
  const [deleteId, setDeleteId] = useState<number>();
  const [error, setError] = useState("");
  const { message } = App.useApp();
  const values = Form.useWatch([], form) || {};
  useEffect(() => {
    if (resource.data && !initialized.current) {
      let draft: Row | undefined;
      try {
        draft = JSON.parse(localStorage.getItem(draftKey) || "null");
      } catch {}
      form.setFieldsValue(
        draft || {
          ...resource.data.release,
          is_mandatory: !!resource.data.release.is_mandatory,
          expected_updated_at: resource.data.release.updated_at,
        },
      );
      setSaved(!!draft);
      initialized.current = true;
    }
  }, [resource.data, form]);
  const saveDraft = (_: unknown, all: Row) => {
    localStorage.setItem(draftKey, JSON.stringify(all));
    setSaved(true);
  };
  const publish = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/release", form.getFieldsValue(true));
      localStorage.removeItem(draftKey);
      setSaved(false);
      setConfirm(false);
      initialized.current = false;
      resource.reload();
      message.success("版本已发布");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const saveHistory = async () => {
    try {
      const data = await historyForm.validateFields();
      setBusy(true);
      await api("/release_history/" + edit?.id, data, undefined, "PUT");
      setEdit(undefined);
      resource.reload();
      message.success("历史记录已更新");
    } catch (e) {
      if (e instanceof Error) message.error(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageTitle
        title="版本发布"
        description="先编辑草稿、核对预览，再发布更新。刷新列表不会覆盖草稿。"
        actions={
          <Button
            onClick={() => {
              if (saved) {
                message.info(
                  "草稿已保留；如需采用线上版本，请使用下方“重载线上版本”",
                );
              }
              resource.reload();
            }}
          >
            刷新发布记录
          </Button>
        }
      />
      {resource.error && (
        <Failure message={resource.error} retry={resource.reload} />
      )}
      <div className="editor-layout">
        <section className="surface section-body">
          <Form form={form} layout="vertical" onValuesChange={saveDraft}>
            <Form.Item name="expected_updated_at" hidden>
              <Input />
            </Form.Item>
            {saved && (
              <Alert
                type="info"
                title="草稿已保存在本机"
                description="尚未对客户端生效。关闭页面或重新登录后仍可继续编辑。"
              />
            )}
            <Fields />
            <Space wrap>
              <Button
                type="primary"
                disabled={!initialized.current}
                onClick={async () => {
                  try {
                    const draft = await form.validateFields();
                    if (
                      (draft.download_url && !draft.sha256) ||
                      (draft.portable_url && !draft.portable_sha256)
                    ) {
                      message.error(
                        "已配置下载地址的文件必须填写 SHA-256 校验值。",
                      );
                      return;
                    }
                    setError("");
                    setConfirm(true);
                  } catch {}
                }}
              >
                核对并发布
              </Button>
              <Button
                onClick={() =>
                  Modal.confirm({
                    title: "用线上版本替换本机草稿？",
                    content: "当前未发布的修改将被丢弃。",
                    okText: "替换草稿",
                    onOk: async () => {
                      const fresh = await api("/releases");
                      form.setFieldsValue({
                        ...fresh.release,
                        is_mandatory: !!fresh.release.is_mandatory,
                        expected_updated_at: fresh.release.updated_at,
                      });
                      localStorage.removeItem(draftKey);
                      setSaved(false);
                    },
                  })
                }
              >
                重载线上版本
              </Button>
            </Space>
          </Form>
        </section>
        <aside>
          <div className="release-preview">
            <Tag color="blue">发布预览</Tag>
            <h2>{values.title || "更新标题"}</h2>
            <p>
              v{values.latest_version || "—"} · 最低支持 v
              {values.minimum_version || "—"}
            </p>
            <Tag color={values.is_mandatory ? "orange" : "default"}>
              {values.is_mandatory ? "强制更新" : "普通更新"}
            </Tag>
            <pre>{values.notes || "填写更新内容后在此预览。"}</pre>
            <p className="helper">
              安装版：{values.download_url ? "已配置" : "未配置，官网隐藏"}
              <br />
              便携版：{values.portable_url ? "已配置" : "未配置，官网隐藏"}
            </p>
          </div>
        </aside>
      </div>
      <section className="surface block-gap">
        <div className="section-head">
          <h2>历史发布记录</h2>
          <span className="secondary">修改历史不会替换当前发布版本</span>
        </div>
        <Table
          ref={(table) => {
            if (table) table.nativeElement.tabIndex = 0;
          }}
          rowKey="id"
          loading={resource.loading}
          dataSource={resource.data?.history.items || []}
          pagination={false}
          locale={{ emptyText: empty }}
          columns={[
            { title: "版本", dataIndex: "latest_version" },
            { title: "标题", dataIndex: "title" },
            { title: "发布时间", dataIndex: "published_at", render: date },
            {
              title: "操作",
              render: (_, r: Row) => (
                <Space>
                  <Button
                    type="link"
                    onClick={() => {
                      setEdit(r);
                      historyForm.setFieldsValue({
                        ...r,
                        is_mandatory: !!r.is_mandatory,
                      });
                    }}
                  >
                    编辑
                  </Button>
                  <Button type="link" danger onClick={() => setDeleteId(r.id)}>
                    删除记录
                  </Button>
                </Space>
              ),
            },
          ]}
        />
        <Pager data={resource.data?.history} update={update} />
      </section>
      <Modal
        open={confirm}
        title="确认发布更新"
        confirmLoading={busy}
        onCancel={() => !busy && setConfirm(false)}
        onOk={publish}
        okText="发布版本"
      >
        <p>
          即将发布 v{values.latest_version}。
          {values.is_mandatory
            ? "所有旧版本将要求更新。"
            : `低于 v${values.minimum_version} 的客户端必须更新。`}
        </p>
        <p>
          安装版：{values.download_url ? "已配置" : "未配置"} · 便携版：
          {values.portable_url ? "已配置" : "未配置"}
        </p>
        {error && <Alert type="error" title={error} />}
      </Modal>
      <Modal
        open={!!edit}
        title="编辑历史发布记录"
        width={680}
        confirmLoading={busy}
        onCancel={() => !busy && setEdit(undefined)}
        onOk={saveHistory}
        okText="保存记录"
      >
        <Form form={historyForm} layout="vertical">
          <Fields />
        </Form>
      </Modal>
      <Modal
        open={!!deleteId}
        title="删除这条发布记录？"
        onCancel={() => setDeleteId(undefined)}
        confirmLoading={busy}
        okButtonProps={{ danger: true }}
        okText="删除记录"
        onOk={async () => {
          setBusy(true);
          try {
            await api("/release_history/" + deleteId, {}, undefined, "DELETE");
            setDeleteId(undefined);
            resource.reload();
          } catch (e) {
            message.error((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>仅删除历史记录，当前客户端更新配置不变。</p>
      </Modal>
    </>
  );
}
