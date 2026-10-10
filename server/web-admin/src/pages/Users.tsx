import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Dropdown,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
} from "antd";
import {
  api,
  date,
  operationId,
  plans,
  planName,
  type Page,
  type Row,
} from "../api";
import {
  AuditDetail,
  Countdown,
  DateFilter,
  empty,
  Failure,
  Filter,
  MemberStatus,
  PageTitle,
  Pager,
  Pending,
  Search,
  useQuery,
  useResource,
  useSelection,
} from "../shared";
import MembershipDialog, { actions } from "../MembershipDialog";

function Detail({
  id,
  onChanged,
  revision,
  onOperate,
}: {
  id: number;
  revision: number;
  onChanged: () => void;
  onOperate: (action: string) => void;
}) {
  const resource = useResource(`/users/${id}?revision=${revision}`);
  const u = resource.data?.user;
  const { message } = App.useApp();
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [password, setPassword] = useState(false);
  const [passwordForm] = Form.useForm();
  useEffect(() => {
    if (u) setNote(u.note);
  }, [u]);
  const saveNote = async () => {
    setSaving(true);
    try {
      const preview = await api("/membership/preview", {
        operation_id: operationId(),
        user_ids: [id],
        action: "note",
        note,
      });
      await api("/membership/commit", { operation_id: preview.operation_id });
      message.success("备注已保存");
      onChanged();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const savePassword = async () => {
    try {
      const values = await passwordForm.validateFields();
      setSaving(true);
      await api("/user_action", {
        user_id: id,
        action: "change_password",
        new_password: values.password,
      });
      message.success("密码已重置，客户端会话已退出");
      setPassword(false);
      passwordForm.resetFields();
      onChanged();
    } catch (e) {
      if (e instanceof Error) message.error(e.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Pending
      loading={resource.loading}
      error={resource.error}
      retry={resource.reload}
    >
      {u && (
        <>
          <div className="detail-section">
            <div className="detail-top">
              <div>
                <h2>{u.username}</h2>
                <span className="secondary">
                  用户 #{u.id} · 注册于 {date(u.created_at)}
                </span>
              </div>
              <MemberStatus user={u} />
            </div>
            <div className="detail-actions">
              <Button type="primary" onClick={() => onOperate("grant")}>
                续费 / 开通
              </Button>
              <Button onClick={() => onOperate("adjust_expiry")}>
                调整到期日
              </Button>
              <Dropdown
                menu={{
                  items: [
                    { key: "revoke", label: "撤销会员", danger: true },
                    {
                      key: u.is_banned ? "unban" : "ban",
                      label: u.is_banned ? "解除封禁" : "封禁账号",
                      danger: !u.is_banned,
                    },
                    { key: "password", label: "重置密码" },
                  ],
                  onClick: ({ key }) =>
                    key === "password" ? setPassword(true) : onOperate(key),
                }}
              >
                <Button>更多操作</Button>
              </Dropdown>
            </div>
          </div>
          <Tabs
            items={[
              {
                key: "profile",
                label: "账号与会员",
                children: (
                  <>
                    <div className="detail-section">
                      <Descriptions
                        column={1}
                        items={[
                          {
                            key: "plan",
                            label: "会员套餐",
                            children: planName(u.plan),
                          },
                          {
                            key: "expiry",
                            label: "到期时间",
                            children:
                              u.is_member && u.plan === "permanent"
                                ? "永久有效"
                                : date(u.member_expires_at),
                          },
                          {
                            key: "account",
                            label: "账号状态",
                            children: u.is_banned
                              ? "已封禁，续费不会解除封禁"
                              : "正常",
                          },
                        ]}
                      />
                      <Form layout="vertical">
                        <Form.Item label="用户备注">
                          <Input.TextArea
                            maxLength={1000}
                            showCount
                            autoSize={{ minRows: 3, maxRows: 6 }}
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                          />
                        </Form.Item>
                        <Button
                          loading={saving}
                          disabled={note === u.note}
                          onClick={saveNote}
                        >
                          保存备注
                        </Button>
                      </Form>
                    </div>
                    <div className="detail-section">
                      <h3>设备与会话</h3>
                      <Descriptions
                        column={1}
                        items={[
                          {
                            key: "name",
                            label: "设备名称",
                            children: u.device_name || "未绑定",
                          },
                          {
                            key: "id",
                            label: "设备 ID",
                            children: (
                              <span className="wrap">{u.device_id || "—"}</span>
                            ),
                          },
                          {
                            key: "bound",
                            label: "绑定时间",
                            children: date(u.device_bound_at),
                          },
                          {
                            key: "cooldown",
                            label: "换绑冷却",
                            children: (
                              <Countdown
                                until={u.device_rebind_cooldown_until}
                              />
                            ),
                          },
                          {
                            key: "sessions",
                            label: "有效会话",
                            children: resource.data?.active_sessions,
                          },
                        ]}
                      />
                      <Space wrap>
                        <Button onClick={() => onOperate("reset_device")}>
                          解绑设备
                        </Button>
                        <Button
                          onClick={() => onOperate("reset_device_cooldown")}
                        >
                          解除冷却
                        </Button>
                      </Space>
                    </div>
                  </>
                ),
              },
              {
                key: "redemptions",
                label: "兑换记录",
                children: (
                  <>
                    <p className="helper">
                      最近 25 条。
                      <a href={`/admin/codes?used_by=${id}`}>
                        查看全部兑换记录 →
                      </a>
                    </p>
                    <Table
                      rowKey="code"
                      size="middle"
                      pagination={false}
                      locale={{ emptyText: empty }}
                      dataSource={resource.data?.redemptions}
                      columns={[
                        {
                          title: "兑换码",
                          dataIndex: "code",
                          render: (v) => <span className="copyable">{v}</span>,
                        },
                        { title: "套餐", dataIndex: "plan", render: planName },
                        {
                          title: "兑换时间",
                          dataIndex: "used_at",
                          render: date,
                        },
                      ]}
                    />
                  </>
                ),
              },
              {
                key: "timeline",
                label: "操作历史",
                children: (
                  <>
                    <p className="helper">
                      最近 25 条。
                      <a
                        href={`/admin/audit?q=${encodeURIComponent(u.username)}`}
                      >
                        查看完整操作历史 →
                      </a>
                    </p>
                    <ul className="details-timeline">
                      {resource.data?.timeline.map((item: Row) => (
                        <li key={item.id}>
                          <time>
                            {date(item.created_at)} · {item.actor}
                          </time>
                          <b>{item.action}</b>
                          <AuditDetail value={item.detail} />
                        </li>
                      ))}
                    </ul>
                    {!resource.data?.timeline.length && empty}
                  </>
                ),
              },
            ]}
          />
          <Modal
            open={password}
            title="重置登录密码"
            onCancel={() => !saving && setPassword(false)}
            onOk={savePassword}
            confirmLoading={saving}
            okText="重置并退出会话"
          >
            <p>该用户的当前客户端会话会被退出。新密码不会出现在操作记录中。</p>
            <Form form={passwordForm} layout="vertical">
              <Form.Item
                name="password"
                label="新密码"
                rules={[{ required: true, min: 6, max: 256 }]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </Pending>
  );
}

export default function Users() {
  const { params, query, update } = useQuery();
  const resource = useResource<Page>("/users?" + query);
  const selection = useSelection(query, 100);
  const navigate = useNavigate();
  const location = useLocation();
  const id = Number(location.pathname.match(/\/users\/(\d+)/)?.[1]);
  const [operation, setOperation] = useState<{
    ids: number[];
    action: string;
  }>();
  const [revision, setRevision] = useState(0);
  const trigger = useRef<HTMLElement | null>(null);
  const refresh = () => {
    resource.reload();
    setRevision((x) => x + 1);
  };
  return (
    <>
      <PageTitle
        title="用户与会员"
        description="查找账号、处理会员与设备问题。账号封禁与会员资格独立管理。"
        actions={
          <Button onClick={resource.reload} loading={resource.loading}>
            刷新列表
          </Button>
        }
      />
      {!!selection.keys.length && (
        <div className="selection-bar">
          <span>
            已选 <strong>{selection.keys.length}</strong> 位用户（跨页保留）
          </span>
          <Space wrap>
            <Button
              type="primary"
              onClick={() =>
                setOperation({
                  ids: selection.keys.map(Number),
                  action: "grant",
                })
              }
            >
              批量续费
            </Button>
            <Dropdown
              menu={{
                items: ["revoke", "ban", "unban", "reset_device_cooldown"].map(
                  (key) => ({ key, label: actions[key].label }),
                ),
                onClick: ({ key }) =>
                  setOperation({
                    ids: selection.keys.map(Number),
                    action: key,
                  }),
              }}
            >
              <Button>批量操作</Button>
            </Dropdown>
            <Button type="text" onClick={selection.clear}>
              清空选择
            </Button>
          </Space>
        </div>
      )}
      <section className="surface user-table">
        <div className="filterbar">
          <Search
            value={params.get("q") || ""}
            onChange={(q) => update({ q })}
            placeholder="搜索账号、用户 ID、设备或备注"
          />
          <Filter
            label="会员状态"
            value={params.get("status") || ""}
            onChange={(status) => update({ status })}
            options={[
              { value: "active", label: "有效会员" },
              { value: "expiring", label: "7 天内到期" },
              { value: "expired", label: "已到期" },
              { value: "inactive", label: "未生效 / 未开通" },
            ]}
          />
          <Filter
            label="账号状态"
            value={params.get("account") || ""}
            onChange={(account) => update({ account })}
            options={[
              { value: "normal", label: "正常账号" },
              { value: "banned", label: "封禁账号" },
            ]}
          />
          <Filter
            label="会员套餐"
            value={params.get("plan") || ""}
            onChange={(plan) => update({ plan })}
            options={plans}
          />
          <Filter
            label="设备状态"
            value={params.get("device") || ""}
            onChange={(device) => update({ device })}
            options={[
              { value: "bound", label: "已绑定" },
              { value: "unbound", label: "未绑定" },
              { value: "cooldown", label: "冷却中" },
            ]}
          />
          <DateFilter
            params={params}
            update={update}
            prefix="expires"
            label="到期日期"
          />
          <Select
            aria-label="排序"
            value={params.get("sort") || "id_desc"}
            onChange={(sort) => update({ sort })}
            options={[
              { value: "id_desc", label: "最新注册优先" },
              { value: "id_asc", label: "最早注册优先" },
              { value: "expiry_asc", label: "到期时间升序" },
              { value: "expiry_desc", label: "到期时间降序" },
              { value: "name_asc", label: "账号排序" },
            ]}
          />
          {query && (
            <Button type="text" onClick={() => navigate("/admin/users")}>
              重置筛选
            </Button>
          )}
        </div>
        {resource.error ? (
          <div className="section-body">
            <Failure message={resource.error} retry={resource.reload} />
          </div>
        ) : (
          <>
            <div className="mobile-user-list" aria-busy={resource.loading}>
              <div className="mobile-select-all">
                <Checkbox
                  checked={
                    !!resource.data?.items.length &&
                    resource.data.items.every((u) =>
                      selection.keys.includes(u.id),
                    )
                  }
                  onChange={(e) =>
                    selection.selection.onChange(
                      e.target.checked
                        ? Array.from(
                            new Set([
                              ...selection.keys,
                              ...(resource.data?.items.map((u) => u.id) || []),
                            ]),
                          )
                        : selection.keys.filter(
                            (id) =>
                              !resource.data?.items.some((u) => u.id === id),
                          ),
                    )
                  }
                >
                  全选本页
                </Checkbox>
                <span className="secondary">
                  {resource.loading ? "正在加载…" : "25 / 50 / 100 条分页"}
                </span>
              </div>
              {resource.data?.items.map((u) => (
                <article className="mobile-user" key={u.id}>
                  <div className="mobile-user-heading">
                    <Checkbox
                      aria-label={"选择 " + u.username}
                      checked={selection.keys.includes(u.id)}
                      onChange={(e) =>
                        selection.selection.onChange(
                          e.target.checked
                            ? [...selection.keys, u.id]
                            : selection.keys.filter((id) => id !== u.id),
                        )
                      }
                    />
                    <div>
                      <Button
                        type="link"
                        className="account-button"
                        onClick={(e) => {
                          trigger.current = e.currentTarget;
                          navigate(`/admin/users/${u.id}?${query}`);
                        }}
                      >
                        {u.username}
                      </Button>
                      <span className="subline">#{u.id}</span>
                    </div>
                  </div>
                  <MemberStatus user={u} />
                  <div className="mobile-user-expiry">
                    <span>{planName(u.plan)}</span>
                    <span>
                      {u.is_member && u.plan === "permanent"
                        ? "永久有效"
                        : date(u.member_expires_at)}
                    </span>
                  </div>
                  {u.note && <p className="helper wrap">{u.note}</p>}
                </article>
              ))}
              {!resource.loading && !resource.data?.items.length && empty}
            </div>
            <Table
              className="desktop-user-list"
              rowKey="id"
              loading={resource.loading}
              pagination={false}
              dataSource={resource.data?.items || []}
              rowSelection={selection.selection}
              locale={{ emptyText: empty }}
              columns={[
                {
                  title: "账号",
                  dataIndex: "username",
                  width: 210,
                  render: (_: string, u: Row) => (
                    <>
                      <Button
                        type="link"
                        className="account-button"
                        onClick={(e) => {
                          trigger.current = e.currentTarget;
                          navigate(`/admin/users/${u.id}?${query}`);
                        }}
                      >
                        {u.username}
                      </Button>
                      <span className="subline">
                        #{u.id}
                        {u.note ? " · " + u.note : ""}
                      </span>
                    </>
                  ),
                },
                {
                  title: "会员与账号",
                  dataIndex: "membership_status",
                  width: 180,
                  render: (_: string, u: Row) => (
                    <>
                      <MemberStatus user={u} />
                      <span className="subline">{planName(u.plan)}</span>
                    </>
                  ),
                },
                {
                  title: "到期时间",
                  dataIndex: "member_expires_at",
                  width: 170,
                  render: (v: string, u: Row) =>
                    u.is_member && u.plan === "permanent"
                      ? "永久有效"
                      : date(v),
                },
                {
                  title: "设备",
                  dataIndex: "device_name",
                  responsive: ["lg"],
                  render: (v: string, u: Row) => (
                    <>
                      <span className="wrap">{v || "未绑定"}</span>
                      {u.device_id && (
                        <span className="subline">
                          <Countdown until={u.device_rebind_cooldown_until} />
                        </span>
                      )}
                    </>
                  ),
                },
                {
                  title: "操作",
                  key: "actions",
                  width: 90,
                  responsive: ["md"],
                  render: (_: unknown, u: Row) => (
                    <Button
                      type="link"
                      onClick={() =>
                        setOperation({ ids: [u.id], action: "grant" })
                      }
                    >
                      续费
                    </Button>
                  ),
                },
              ]}
            />
          </>
        )}
        <Pager data={resource.data} update={update} />
      </section>
      <Drawer
        className="user-drawer"
        open={!!id}
        size={680}
        title="用户详情"
        onClose={() =>
          navigate("/admin/users" + (query ? "?" + query : ""), {
            replace: true,
          })
        }
        afterOpenChange={(open) => {
          if (!open) trigger.current?.focus();
        }}
        destroyOnHidden
      >
        {!!id && (
          <Detail
            id={id}
            revision={revision}
            onChanged={refresh}
            onOperate={(action) => setOperation({ ids: [id], action })}
          />
        )}
      </Drawer>
      {operation && (
        <MembershipDialog
          {...operation}
          onClose={() => setOperation(undefined)}
          onDone={refresh}
        />
      )}
    </>
  );
}
