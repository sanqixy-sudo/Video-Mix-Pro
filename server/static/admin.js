(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const state = {
    plans: {},
    release: null,
    releaseHistory: [],
    pricing: [],
    codeBatches: [],
    users: { items: [], page: 1, pages: 1, total: 0 },
    codes: { items: [], page: 1, pages: 1, total: 0 },
    audit: { items: [], actions: [], page: 1, pages: 1, total: 0 },
    selectedUsers: new Set(),
    selectedCodes: new Set(),
    passwordUser: null,
  };
  const byId = (id) => document.getElementById(id);
  const errorBox = byId("adminError");
  const toast = byId("toast");
  let toastTimer = 0;

  function node(tag, options = {}, children = []) {
    const element = document.createElement(tag);
    if (options.className) element.className = options.className;
    if (options.text !== undefined) element.textContent = String(options.text);
    if (options.title) element.title = options.title;
    if (options.type) element.type = options.type;
    if (options.value !== undefined) element.value = String(options.value);
    for (const child of children) if (child !== null && child !== undefined) element.append(child);
    return element;
  }

  function showError(message = "") {
    errorBox.textContent = message;
    errorBox.classList.toggle("show", Boolean(message));
  }

  function notify(message) {
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2800);
  }

  function errorMessage(payload, status) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    if (typeof payload?.error === "string") return payload.error;
    return `请求失败：HTTP ${status}`;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if ((options.method || "GET").toUpperCase() !== "GET") headers.set("X-CSRF-Token", csrfToken);
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    const text = await response.text();
    let payload = {};
    if (text) {
      try { payload = JSON.parse(text); } catch { payload = { detail: text }; }
    }
    if (!response.ok) {
      if (response.status === 401) window.location.reload();
      throw new Error(errorMessage(payload, response.status));
    }
    return payload;
  }

  function url(path, params) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    return `${path}?${search.toString()}`;
  }

  function formatDate(value, fallback = "—") {
    if (!value) return fallback;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
  }

  function formatDuration(seconds) {
    let remaining = Math.max(0, Number(seconds) || 0);
    if (!remaining) return "已解除";
    const hours = Math.floor(remaining / 3600);
    remaining %= 3600;
    const minutes = Math.floor(remaining / 60);
    const secs = remaining % 60;
    return [hours ? `${hours} 小时` : "", minutes ? `${minutes} 分` : "", !hours && secs ? `${secs} 秒` : ""].filter(Boolean).join(" ");
  }

  function memberIsActive(user) {
    if (typeof user.active === "boolean") return user.active;
    if (!user.is_member || user.is_banned) return false;
    if (user.plan === "permanent") return true;
    const expires = new Date(user.member_expires_at || "").getTime();
    return Number.isFinite(expires) && expires > Date.now();
  }

  function badge(label, tone = "") {
    return node("span", { className: `badge ${tone}`.trim(), text: label });
  }

  function planLabel(plan, customDays) {
    return plan === "custom" ? `自定义 ${customDays || 0} 天` : state.plans[plan] || plan || "—";
  }

  function empty(shell, text) {
    shell.replaceChildren(node("div", { className: "empty-state", text }));
  }

  function checkbox(checked, onChange, label) {
    const input = node("input", { type: "checkbox" });
    input.checked = checked;
    input.setAttribute("aria-label", label);
    input.addEventListener("change", () => onChange(input.checked));
    return input;
  }

  function debounce(fn, delay = 280) {
    let timer = 0;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), delay);
    };
  }

  function renderPagination(targetId, data, onPage) {
    const target = byId(targetId);
    target.replaceChildren();
    if (!data.total) return;
    const summary = node("span", { text: `共 ${data.total} 条 · 第 ${data.page} / ${data.pages} 页` });
    const controls = node("div");
    const previous = node("button", { className: "admin-button ghost small", text: "上一页", type: "button" });
    const next = node("button", { className: "admin-button ghost small", text: "下一页", type: "button" });
    previous.disabled = data.page <= 1;
    next.disabled = data.page >= data.pages;
    previous.addEventListener("click", () => onPage(data.page - 1));
    next.addEventListener("click", () => onPage(data.page + 1));
    controls.append(previous, next);
    target.append(summary, controls);
  }

  function tableHead(labels, selectAll) {
    const head = node("thead");
    const row = node("tr");
    if (selectAll) row.append(node("th", { className: "check-cell" }, [selectAll]));
    labels.forEach((label) => row.append(node("th", { text: label })));
    head.append(row);
    return head;
  }

  function updateUserSelectionCount() {
    byId("selectedUsersCount").textContent = String(state.selectedUsers.size);
  }

  function updateCodeSelectionCount() {
    byId("selectedCodesCount").textContent = String(state.selectedCodes.size);
  }

  async function loadSummary() {
    const summary = await api("/admin/api/summary");
    state.plans = summary.plans || {};
    state.release = summary.release || null;
    state.releaseHistory = Array.isArray(summary.release_history) ? summary.release_history : [];
    state.pricing = Array.isArray(summary.pricing) ? summary.pricing : [];
    state.codeBatches = Array.isArray(summary.code_batches) ? summary.code_batches : [];
    const metrics = summary.metrics || {};
    byId("metricUsers").textContent = String(metrics.users_total ?? 0);
    byId("metricMembers").textContent = String(metrics.members_active ?? 0);
    byId("metricCooldowns").textContent = String(metrics.devices_cooling_down ?? 0);
    byId("metricCodes").textContent = String(metrics.codes_available ?? 0);
    byId("metricRegistrations").textContent = String(metrics.registrations_today ?? 0);
    byId("metricRedeemed").textContent = String(metrics.redeemed_today ?? 0);
    byId("metricExpiring").textContent = String(metrics.members_expiring_7d ?? 0);
    byId("metricCodeIssues").textContent = String((metrics.codes_disabled || 0) + (metrics.codes_expired || 0));
    fillRelease(state.release);
    renderReleaseHistory();
    fillPricing();
    fillBatchFilter();
  }

  function fillBatchFilter() {
    const select = byId("codeBatch");
    const current = select.value || "all";
    const first = node("option", { text: "全部批次", value: "all" });
    select.replaceChildren(first);
    state.codeBatches.forEach((batch) => {
      const option = node("option", { value: batch.batch_id, text: `${batch.batch_id} · ${batch.unused}/${batch.total} 未使用` });
      option.title = batch.note || "";
      select.append(option);
    });
    select.value = [...select.options].some((option) => option.value === current) ? current : "all";
  }

  async function loadUsers(page = 1) {
    const shell = byId("usersTable");
    shell.setAttribute("aria-busy", "true");
    const payload = await api(url("/admin/api/users", {
      q: byId("userSearch").value.trim(),
      status: byId("userStatus").value,
      plan: byId("userPlan").value,
      device: byId("userDevice").value,
      page,
      page_size: 25,
    }));
    state.users = payload;
    state.selectedUsers.clear();
    updateUserSelectionCount();
    renderUsers();
    renderPagination("usersPagination", state.users, (nextPage) => void run(() => loadUsers(nextPage)));
    shell.removeAttribute("aria-busy");
  }

  function actionButton(label, action, user, tone = "") {
    const button = node("button", { className: tone, text: label, type: "button" });
    button.addEventListener("click", () => void runUserAction(user, action));
    return button;
  }

  async function runUserAction(user, action) {
    const labels = {
      grant: "开通会员", revoke: "撤销会员", ban: "封禁账号", unban: "解除封禁",
      reset_device: "解绑设备", reset_device_cooldown: "解除换绑冷却", delete_user: "删除用户", change_password: "修改密码",
    };
    if (action === "change_password") return openPasswordDialog(user);
    const payload = { user_id: user.id, action };
    if (action === "grant") {
      const plan = window.prompt("会员类型：month / quarter / half_year / year / permanent / custom", user.plan || "month");
      if (!plan) return;
      if (!Object.prototype.hasOwnProperty.call(state.plans, plan)) return showError("会员类型无效");
      payload.plan = plan;
      if (plan === "custom") {
        const customDays = window.prompt("请输入自定义天数（1 - 36500）", "30");
        if (!customDays) return;
        payload.custom_days = Number(customDays);
      }
    } else if (!window.confirm(`确定对“${user.username}”执行“${labels[action]}”吗？`)) return;
    await run(async () => {
      await api("/admin/api/user_action", { method: "POST", body: JSON.stringify(payload) });
      notify(`${labels[action]}成功`);
      await Promise.all([loadSummary(), loadUsers(state.users.page)]);
    });
  }

  function openPasswordDialog(user) {
    state.passwordUser = user;
    byId("passwordDialogTitle").textContent = `修改 ${user.username} 的密码`;
    byId("newUserPassword").value = "";
    byId("confirmUserPassword").value = "";
    byId("passwordDialog").showModal();
    byId("newUserPassword").focus();
  }

  function renderUsers() {
    const shell = byId("usersTable");
    shell.replaceChildren();
    const users = state.users.items || [];
    if (!users.length) return empty(shell, "没有匹配的用户");
    const table = node("table", { className: "admin-table" });
    const selectAll = checkbox(false, (checked) => {
      users.forEach((user) => checked ? state.selectedUsers.add(user.id) : state.selectedUsers.delete(user.id));
      renderUsers();
      updateUserSelectionCount();
    }, "选择本页用户");
    selectAll.checked = users.every((user) => state.selectedUsers.has(user.id));
    table.append(tableHead(["用户", "会员", "设备", "换绑冷却", "注册时间", "操作"], selectAll));
    const body = node("tbody");
    users.forEach((user) => {
      const row = node("tr");
      const selected = checkbox(state.selectedUsers.has(user.id), (checked) => {
        checked ? state.selectedUsers.add(user.id) : state.selectedUsers.delete(user.id);
        updateUserSelectionCount();
      }, `选择用户 ${user.username}`);
      const identity = node("td", {}, [node("strong", { text: user.username }), node("small", { text: `ID ${user.id}` })]);
      const detail = node("button", { className: "inline-link", text: "查看详情", type: "button" });
      detail.addEventListener("click", () => void showUserDetail(user.id));
      identity.append(detail);
      const membership = node("td");
      if (user.is_banned) membership.append(badge("已封禁", "danger"));
      else if (memberIsActive(user)) membership.append(badge(state.plans[user.plan] || user.plan || "有效会员", "success"));
      else membership.append(badge("未开通"));
      membership.append(node("small", { text: user.plan === "permanent" ? "永久有效" : formatDate(user.member_expires_at, "无到期时间") }));
      const device = node("td", {}, [
        node("strong", { text: user.device_name || "未绑定" }),
        node("small", { text: user.device_id || "—", title: user.device_id || "" }),
      ]);
      if (user.device_bound_at) device.append(node("small", { text: `绑定：${formatDate(user.device_bound_at)}` }));
      const cooldown = node("td");
      if (user.device_rebind_remaining_seconds > 0) {
        cooldown.append(badge(formatDuration(user.device_rebind_remaining_seconds), "warning"));
        cooldown.append(node("small", { text: `截止：${formatDate(user.device_rebind_cooldown_until)}` }));
      } else cooldown.append(badge("无冷却", "success"));
      const actionGroup = node("div", { className: "table-actions" });
      actionGroup.append(actionButton(memberIsActive(user) ? "续期开通" : "开通会员", "grant", user));
      if (user.is_member) actionGroup.append(actionButton("撤销会员", "revoke", user, "warning"));
      actionGroup.append(actionButton(user.is_banned ? "解封" : "封禁", user.is_banned ? "unban" : "ban", user, user.is_banned ? "" : "warning"));
      if (user.device_rebind_remaining_seconds > 0) actionGroup.append(actionButton("解除冷却", "reset_device_cooldown", user, "warning"));
      if (user.device_id) actionGroup.append(actionButton("解绑设备", "reset_device", user));
      actionGroup.append(actionButton("修改密码", "change_password", user));
      actionGroup.append(actionButton("删除", "delete_user", user, "danger"));
      row.append(node("td", { className: "check-cell" }, [selected]), identity, membership, device, cooldown, node("td", { text: formatDate(user.created_at) }), node("td", {}, [actionGroup]));
      body.append(row);
    });
    table.append(body);
    shell.append(table);
  }

  async function showUserDetail(userId) {
    const dialog = byId("userDetailDialog");
    const body = byId("userDetailBody");
    body.replaceChildren(node("div", { className: "loading-state", text: "正在加载详情…" }));
    dialog.showModal();
    await run(async () => {
      const data = await api(`/admin/api/users/${userId}`);
      const user = data.user;
      byId("detailUsername").textContent = user.username;
      const facts = node("div", { className: "detail-facts" });
      [
        ["会员状态", memberIsActive(user) ? `${state.plans[user.plan] || user.plan} · ${user.plan === "permanent" ? "永久" : formatDate(user.member_expires_at)}` : "非有效会员"],
        ["设备", user.device_name ? `${user.device_name} · ${user.device_id || "无设备码"}` : "未绑定"],
        ["换绑冷却", user.device_rebind_remaining_seconds > 0 ? formatDuration(user.device_rebind_remaining_seconds) : "无冷却"],
        ["活动会话", data.active_sessions],
        ["注册时间", formatDate(user.created_at)],
        ["最近更新", formatDate(user.updated_at)],
      ].forEach(([label, value]) => facts.append(node("article", {}, [node("span", { text: label }), node("strong", { text: value })])));
      const redemptions = node("div", { className: "detail-block" }, [node("h3", { text: "兑换记录" })]);
      if (!data.redemptions.length) redemptions.append(node("p", { className: "muted-copy", text: "暂无兑换记录" }));
      data.redemptions.forEach((item) => redemptions.append(node("article", { className: "timeline-item" }, [
        node("strong", { text: item.code }),
        node("span", { text: `${planLabel(item.plan, item.custom_days)} · ${formatDate(item.used_at)} · 批次 ${item.batch_id || "legacy"}` }),
      ])));
      const timeline = node("div", { className: "detail-block" }, [node("h3", { text: "操作时间线" })]);
      if (!data.timeline.length) timeline.append(node("p", { className: "muted-copy", text: "暂无操作记录" }));
      data.timeline.forEach((item) => timeline.append(node("article", { className: "timeline-item" }, [
        node("strong", { text: item.action }),
        node("span", { text: `${formatDate(item.created_at)} · ${item.actor} · ${item.detail || "无详情"}` }),
      ])));
      body.replaceChildren(facts, redemptions, timeline);
    });
  }

  async function runUserBatch() {
    if (!state.selectedUsers.size) return notify("请先选择用户");
    const action = byId("userBatchAction").value;
    const payload = { action, user_ids: [...state.selectedUsers] };
    if (action === "grant") {
      payload.plan = byId("userBatchPlan").value;
      if (payload.plan === "custom") payload.custom_days = Number(byId("userBatchCustomDays").value);
    }
    if (!window.confirm(`确定对 ${payload.user_ids.length} 位用户执行批量操作吗？`)) return;
    await run(async () => {
      const result = await api("/admin/api/user_batch_action", { method: "POST", body: JSON.stringify(payload) });
      notify(`批量操作完成，已处理 ${result.affected || 0} 位用户`);
      await Promise.all([loadSummary(), loadUsers(state.users.page), loadAudit(1)]);
    });
  }

  function codeStatus(code) {
    if (code.used_by) return ["已使用", "warning"];
    if (code.is_disabled) return ["已停用", "danger"];
    if (code.expires_at && new Date(code.expires_at).getTime() <= Date.now()) return ["已过期", "danger"];
    return ["可用", "success"];
  }

  async function loadCodes(page = 1) {
    const payload = await api(url("/admin/api/codes", {
      q: byId("codeSearch").value.trim(),
      status: byId("codeStatus").value,
      batch_id: byId("codeBatch").value,
      page,
      page_size: 25,
    }));
    state.codes = payload;
    state.selectedCodes.clear();
    updateCodeSelectionCount();
    renderCodes();
    renderPagination("codesPagination", state.codes, (nextPage) => void run(() => loadCodes(nextPage)));
    byId("exportCodesButton").href = url("/admin/api/codes/export", {
      status: byId("codeStatus").value,
      batch_id: byId("codeBatch").value,
    });
  }

  function renderCodes() {
    const shell = byId("codesTable");
    shell.replaceChildren();
    const codes = state.codes.items || [];
    if (!codes.length) return empty(shell, "没有匹配的兑换码");
    const table = node("table", { className: "admin-table" });
    const selectAll = checkbox(false, (checked) => {
      codes.forEach((code) => checked ? state.selectedCodes.add(code.code) : state.selectedCodes.delete(code.code));
      renderCodes();
      updateCodeSelectionCount();
    }, "选择本页兑换码");
    selectAll.checked = codes.every((code) => state.selectedCodes.has(code.code));
    table.append(tableHead(["兑换码", "会员类型", "状态", "批次 / 失效", "创建时间", "备注"], selectAll));
    const body = node("tbody");
    codes.forEach((code) => {
      const selected = checkbox(state.selectedCodes.has(code.code), (checked) => {
        checked ? state.selectedCodes.add(code.code) : state.selectedCodes.delete(code.code);
        updateCodeSelectionCount();
      }, `选择兑换码 ${code.code}`);
      const codeCell = node("td", {}, [node("strong", { text: code.code })]);
      const copy = node("button", { className: "inline-link", text: "复制", type: "button" });
      copy.addEventListener("click", async () => {
        await navigator.clipboard.writeText(code.code);
        notify("兑换码已复制");
      });
      codeCell.append(copy);
      const status = node("td");
      const [label, tone] = codeStatus(code);
      status.append(badge(label, tone));
      if (code.used_by_username_snapshot) status.append(node("small", { text: `账号：${code.used_by_username_snapshot}` }));
      if (code.used_at) status.append(node("small", { text: formatDate(code.used_at) }));
      const batch = node("td", {}, [
        node("strong", { text: code.batch_id || "legacy" }),
        node("small", { text: code.expires_at ? `失效：${formatDate(code.expires_at)}` : "长期可兑换" }),
      ]);
      body.append(node("tr", {}, [
        node("td", { className: "check-cell" }, [selected]), codeCell,
        node("td", { text: planLabel(code.plan, code.custom_days) }), status, batch,
        node("td", { text: formatDate(code.created_at) }), node("td", { text: code.note || "—" }),
      ]));
    });
    table.append(body);
    shell.append(table);
  }

  async function runCodeAction(action) {
    if (!state.selectedCodes.size) return notify("请先选择兑换码");
    const labels = { disable: "停用", enable: "恢复", delete_unused: "删除未使用 Key" };
    if (!window.confirm(`确定对 ${state.selectedCodes.size} 个 Key 执行“${labels[action]}”吗？已使用 Key 不会被删除。`)) return;
    await run(async () => {
      const result = await api("/admin/api/code_action", {
        method: "POST",
        body: JSON.stringify({ action, codes: [...state.selectedCodes] }),
      });
      notify(`操作完成：匹配 ${result.matched || 0}，处理 ${result.affected || 0}`);
      await Promise.all([loadSummary(), loadCodes(state.codes.page), loadAudit(1)]);
    });
  }

  function fillRelease(release) {
    if (!release) return;
    byId("latestVersion").value = release.latest_version || "";
    byId("minimumVersion").value = release.minimum_version || "";
    byId("releaseTitleInput").value = release.title || "";
    byId("downloadUrl").value = release.download_url || "";
    byId("releaseSha256").value = release.sha256 || "";
    byId("releaseNotesInput").value = release.notes || "";
    byId("mandatoryUpdate").checked = Boolean(release.is_mandatory);
    byId("releaseUpdatedAt").textContent = release.updated_at ? `最后更新：${formatDate(release.updated_at)}` : "";
  }

  function fillPricing() {
    const ids = { month: "priceMonth", quarter: "priceQuarter", year: "priceYear", permanent: "pricePermanent" };
    state.pricing.forEach((item) => {
      if (ids[item.plan]) byId(ids[item.plan]).value = item.price_display || "";
    });
  }

  function openReleaseHistoryDialog(item) {
    byId("historyId").value = String(item.id);
    byId("historyVersion").value = item.latest_version || "";
    byId("historyMinimumVersion").value = item.minimum_version || "";
    byId("historyTitle").value = item.title || "";
    byId("historyDownloadUrl").value = item.download_url || "";
    byId("historySha256").value = item.sha256 || "";
    byId("historyNotes").value = item.notes || "";
    byId("historyMandatory").checked = Boolean(item.is_mandatory);
    byId("releaseHistoryDialog").showModal();
  }

  async function deleteReleaseHistory(item) {
    if (!window.confirm(`确定删除历史版本 v${item.latest_version} 吗？这不会删除当前稳定版配置。`)) return;
    await run(async () => {
      await api(`/admin/api/release_history/${item.id}`, { method: "DELETE" });
      notify("历史版本已删除");
      await Promise.all([loadSummary(), loadAudit(1)]);
    });
  }

  function renderReleaseHistory() {
    const shell = byId("releaseHistoryTable");
    shell.replaceChildren();
    if (!state.releaseHistory.length) return empty(shell, "暂无发布历史，保存一次发布信息后会自动记录");
    const table = node("table", { className: "admin-table history-table" });
    table.append(tableHead(["版本", "最低版本", "标题 / 说明", "下载 / 校验", "发布时间", "发布人", "操作"]));
    const body = node("tbody");
    state.releaseHistory.forEach((item) => {
      const releaseInfo = node("td", {}, [node("strong", { text: item.title || "—" }), node("small", { text: item.notes || "无更新说明" })]);
      const download = node("td", {}, [node("small", { text: item.download_url || "未设置下载地址", title: item.download_url || "" }), node("small", { text: item.sha256 ? `SHA-256 ${item.sha256}` : "无校验值" })]);
      const actions = node("div", { className: "table-actions" });
      const edit = node("button", { text: "编辑", type: "button" });
      const remove = node("button", { className: "danger", text: "删除", type: "button" });
      edit.addEventListener("click", () => openReleaseHistoryDialog(item));
      remove.addEventListener("click", () => void deleteReleaseHistory(item));
      actions.append(edit, remove);
      body.append(node("tr", {}, [
        node("td", {}, [badge(item.latest_version, item.is_mandatory ? "warning" : "success")]),
        node("td", { text: item.minimum_version }), releaseInfo, download,
        node("td", { text: formatDate(item.published_at) }), node("td", { text: item.published_by || "—" }), node("td", {}, [actions]),
      ]));
    });
    table.append(body);
    shell.append(table);
  }

  async function loadAudit(page = 1) {
    const payload = await api(url("/admin/api/audit", {
      q: byId("auditSearch").value.trim(),
      action: byId("auditAction").value,
      page,
      page_size: 25,
    }));
    state.audit = payload;
    fillAuditActions();
    renderAudit();
    renderPagination("auditPagination", state.audit, (nextPage) => void run(() => loadAudit(nextPage)));
  }

  function fillAuditActions() {
    const select = byId("auditAction");
    const current = select.value || "all";
    select.replaceChildren(node("option", { value: "all", text: "全部操作" }));
    state.audit.actions.forEach((action) => select.append(node("option", { value: action, text: action })));
    select.value = [...select.options].some((option) => option.value === current) ? current : "all";
  }

  function renderAudit() {
    const shell = byId("auditTable");
    shell.replaceChildren();
    if (!state.audit.items.length) return empty(shell, "没有匹配的审计日志");
    const table = node("table", { className: "admin-table audit-table" });
    table.append(tableHead(["时间", "操作", "操作者", "目标", "详情", "IP"]));
    const body = node("tbody");
    state.audit.items.forEach((item) => body.append(node("tr", {}, [
      node("td", { text: formatDate(item.created_at) }),
      node("td", {}, [badge(item.action, item.action.includes("delete") || item.action.includes("ban") ? "danger" : "")]),
      node("td", { text: item.actor || "—" }), node("td", { text: item.target || "—" }),
      node("td", { text: item.detail || "—" }), node("td", { text: item.ip || "—" }),
    ])));
    table.append(body);
    shell.append(table);
  }

  async function refreshAll() {
    showError();
    await loadSummary();
    await Promise.all([loadUsers(1), loadCodes(1), loadAudit(1)]);
  }

  async function run(task) {
    try {
      showError();
      await task();
    } catch (error) {
      showError(error instanceof Error ? error.message : "操作失败");
    }
  }

  byId("releaseForm").addEventListener("submit", (event) => void run(async () => {
    event.preventDefault();
    const submit = event.submitter;
    if (submit) submit.disabled = true;
    try {
      const result = await api("/admin/api/release", {
        method: "POST",
        body: JSON.stringify({
          latest_version: byId("latestVersion").value.trim(),
          minimum_version: byId("minimumVersion").value.trim(),
          title: byId("releaseTitleInput").value.trim(),
          download_url: byId("downloadUrl").value.trim(),
          sha256: byId("releaseSha256").value.trim(),
          notes: byId("releaseNotesInput").value.trim(),
          is_mandatory: byId("mandatoryUpdate").checked,
        }),
      });
      state.release = result.release;
      fillRelease(state.release);
      notify("发布信息已保存，客户端将按版本号检测更新");
      await Promise.all([loadSummary(), loadAudit(1)]);
    } finally {
      if (submit) submit.disabled = false;
    }
  }));

  byId("pricingForm").addEventListener("submit", (event) => void run(async () => {
    event.preventDefault();
    const submit = event.submitter;
    if (submit) submit.disabled = true;
    try {
      const result = await api("/admin/api/pricing", {
        method: "POST",
        body: JSON.stringify({ prices: {
          month: byId("priceMonth").value.trim(),
          quarter: byId("priceQuarter").value.trim(),
          year: byId("priceYear").value.trim(),
          permanent: byId("pricePermanent").value.trim(),
        } }),
      });
      state.pricing = result.pricing || [];
      fillPricing();
      notify("官网定价已保存");
      await loadAudit(1);
    } finally {
      if (submit) submit.disabled = false;
    }
  }));

  byId("passwordForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void run(async () => {
      const password = byId("newUserPassword").value;
      if (password !== byId("confirmUserPassword").value) throw new Error("两次输入的新密码不一致");
      if (!state.passwordUser) throw new Error("没有选中用户");
      await api("/admin/api/user_action", {
        method: "POST",
        body: JSON.stringify({ user_id: state.passwordUser.id, action: "change_password", new_password: password }),
      });
      byId("passwordDialog").close();
      notify("用户密码已修改，原登录会话已失效");
      await Promise.all([loadUsers(state.users.page), loadAudit(1)]);
    });
  });

  byId("releaseHistoryForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void run(async () => {
      const historyId = Number(byId("historyId").value);
      await api(`/admin/api/release_history/${historyId}`, {
        method: "PUT",
        body: JSON.stringify({
          latest_version: byId("historyVersion").value.trim(),
          minimum_version: byId("historyMinimumVersion").value.trim(),
          title: byId("historyTitle").value.trim(),
          download_url: byId("historyDownloadUrl").value.trim(),
          sha256: byId("historySha256").value.trim(),
          notes: byId("historyNotes").value.trim(),
          is_mandatory: byId("historyMandatory").checked,
        }),
      });
      byId("releaseHistoryDialog").close();
      notify("历史版本已更新");
      await Promise.all([loadSummary(), loadAudit(1)]);
    });
  });

  byId("codeForm").addEventListener("submit", (event) => void run(async () => {
    event.preventDefault();
    const submit = event.submitter;
    if (submit) submit.disabled = true;
    try {
      const rawExpiry = byId("codeExpiresAt").value;
      const result = await api("/admin/api/create_codes", {
        method: "POST",
        body: JSON.stringify({
          plan: byId("plan").value,
          count: Number(byId("codeCount").value),
          custom_days: Number(byId("customDays").value),
          expires_at: rawExpiry ? new Date(rawExpiry).toISOString() : "",
          note: byId("codeNote").value.trim(),
        }),
      });
      byId("newCodes").value = (result.created || []).join("\n");
      byId("generatedBatchId").textContent = `批次 ${result.batch_id || "—"}`;
      notify(`已生成 ${(result.created || []).length} 个兑换码`);
      await Promise.all([loadSummary(), loadCodes(1), loadAudit(1)]);
    } finally {
      if (submit) submit.disabled = false;
    }
  }));

  const reloadUsers = debounce(() => void run(() => loadUsers(1)));
  const reloadCodes = debounce(() => void run(() => loadCodes(1)));
  const reloadAudit = debounce(() => void run(() => loadAudit(1)));
  byId("userSearch").addEventListener("input", reloadUsers);
  ["userStatus", "userPlan", "userDevice"].forEach((id) => byId(id).addEventListener("change", () => void run(() => loadUsers(1))));
  byId("codeSearch").addEventListener("input", reloadCodes);
  ["codeStatus", "codeBatch"].forEach((id) => byId(id).addEventListener("change", () => void run(() => loadCodes(1))));
  byId("auditSearch").addEventListener("input", reloadAudit);
  byId("auditAction").addEventListener("change", () => void run(() => loadAudit(1)));

  byId("plan").addEventListener("change", () => { byId("customDaysField").hidden = byId("plan").value !== "custom"; });
  function updateUserBatchFields() {
    const grant = byId("userBatchAction").value === "grant";
    byId("userBatchPlan").hidden = !grant;
    byId("userBatchCustomDays").hidden = !grant || byId("userBatchPlan").value !== "custom";
  }
  byId("userBatchAction").addEventListener("change", updateUserBatchFields);
  byId("userBatchPlan").addEventListener("change", updateUserBatchFields);
  byId("runUserBatchButton").addEventListener("click", () => void runUserBatch());
  document.querySelectorAll("[data-code-action]").forEach((button) => button.addEventListener("click", () => void runCodeAction(button.dataset.codeAction)));

  byId("refreshButton").addEventListener("click", () => void run(async () => { await refreshAll(); notify("运营数据已刷新"); }));
  byId("copyCodesButton").addEventListener("click", async () => {
    const value = byId("newCodes").value.trim();
    if (!value) return notify("当前没有可复制的新兑换码");
    await navigator.clipboard.writeText(value);
    notify("本次生成的兑换码已复制");
  });
  byId("cleanupSmokeButton").addEventListener("click", () => void run(async () => {
    if (!window.confirm("确定清理 smoke_ 开头的测试账号和带测试备注的未使用兑换码吗？")) return;
    const result = await api("/admin/api/cleanup_smoke", { method: "POST", body: "{}" });
    notify(`已清理 ${result.users_deleted || 0} 个账号、${result.codes_deleted || 0} 个兑换码`);
    await refreshAll();
  }));
  byId("logoutButton").addEventListener("click", () => void run(async () => {
    const result = await api("/admin/logout", { method: "POST", body: "{}" });
    window.location.replace(result.redirect_url || "/");
  }));
  byId("closeUserDetail").addEventListener("click", () => byId("userDetailDialog").close());
  byId("userDetailDialog").addEventListener("click", (event) => {
    if (event.target === byId("userDetailDialog")) byId("userDetailDialog").close();
  });
  byId("closePasswordDialog").addEventListener("click", () => byId("passwordDialog").close());
  byId("closeReleaseHistoryDialog").addEventListener("click", () => byId("releaseHistoryDialog").close());
  [byId("passwordDialog"), byId("releaseHistoryDialog")].forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));

  const navLinks = [...document.querySelectorAll(".admin-sidebar nav a")];
  const sections = navLinks.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    navLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`));
  }, { rootMargin: "-15% 0px -70%", threshold: [0, 0.2, 0.6] });
  sections.forEach((section) => observer.observe(section));

  updateUserBatchFields();
  void run(refreshAll);
  window.setInterval(() => {
    let changed = false;
    state.users.items.forEach((user) => {
      if (user.device_rebind_remaining_seconds > 0) {
        user.device_rebind_remaining_seconds -= 1;
        changed = true;
      }
    });
    if (changed) renderUsers();
  }, 1000);
})();
