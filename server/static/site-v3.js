(() => {
  "use strict";
  const { release, settings, pricing } = JSON.parse(
    document.getElementById("site-data").textContent,
  );
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const available = !!(release.download_url || release.portable_url);
  document
    .querySelectorAll(".download-entry")
    .forEach((el) => (el.hidden = !available));
  const dialog = document.getElementById("contact-dialog");
  let trigger = null;
  const hasContact = !!(settings.contact_value || settings.contact_url);
  for (const plan of pricing) {
    const card = node("article", null, "price-card");
    card.append(node("h3", plan.label + "会员"));
    const price = node("div", plan.price_display || "联系咨询", "price");
    price.append(node("small", plan.period));
    card.append(price, node("p", plan.description));
    if (hasContact) {
      const button = node("button", "联系开通", "button");
      button.onclick = () => {
        trigger = button;
        document.getElementById("contact-title").textContent =
          "开通" + plan.label + "会员";
        document.getElementById("contact-plan").textContent =
          `所选套餐：${plan.label}会员 · ${plan.price_display || "联系咨询"}`;
        dialog.showModal();
      };
      card.append(button);
    }
    document.getElementById("pricing-grid").append(card);
  }
  document.getElementById("contact-label").textContent =
    settings.contact_label || "联系方式";
  document.getElementById("contact-value").textContent = settings.contact_value;
  const link = document.getElementById("contact-link");
  link.hidden = !settings.contact_url;
  if (settings.contact_url) link.href = settings.contact_url;
  const button = document.getElementById("copy-contact");
  button.hidden = !settings.contact_value;
  button.onclick = async () => {
    try {
      await navigator.clipboard.writeText(
        document.getElementById("contact-plan").textContent +
          "\n" +
          settings.contact_value,
      );
      document.getElementById("contact-feedback").textContent =
        "联系方式与所选套餐已复制";
    } catch {
      document.getElementById("contact-feedback").textContent =
        "无法自动复制，请选中上方联系账号手动复制";
    }
  };
  document.getElementById("close-contact").onclick = () => dialog.close();
  dialog.addEventListener("close", () => {
    document.getElementById("contact-feedback").textContent = "";
    trigger?.focus();
  });
  document.getElementById("release-meta").textContent =
    `当前版本 v${release.latest_version} · 更新于 ${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "medium" }).format(new Date(release.updated_at))}`;
  for (const [title, description, url, hash] of [
    [
      "安装版",
      "适合日常安装使用，按安装向导完成设置。",
      release.download_url,
      release.sha256,
    ],
    [
      "便携版",
      "解压到独立目录后运行，便于自行管理软件文件。",
      release.portable_url,
      release.portable_sha256,
    ],
  ]) {
    if (!url) continue;
    const card = node("article", null, "download-card");
    card.append(node("h3", title), node("p", description));
    const link = node("a", "下载" + title + " ↗", "button primary");
    link.href = url;
    card.append(link);
    if (hash) card.append(node("code", "SHA-256\n" + hash));
    document.getElementById("download-grid").append(card);
  }
  document.getElementById("download-empty").hidden = available;
  for (const [id, value] of [
    ["download-notes", settings.download_notes],
    ["help-text", settings.help_text],
  ]) {
    const el = document.getElementById(id);
    el.hidden = !value;
    el.textContent = value || "";
  }
  const toggle = document.querySelector(".menu-toggle"),
    links = document.getElementById("nav-links");
  toggle.onclick = () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    links.classList.toggle("open", open);
  };
  links.addEventListener("click", (e) => {
    if (e.target.closest("a")) {
      toggle.setAttribute("aria-expanded", "false");
      links.classList.remove("open");
    }
  });
})();
