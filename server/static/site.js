(() => {
  const header = document.querySelector(".site-header");
  const menuButton = document.querySelector(".mobile-menu-button");
  const menu = document.querySelector(".nav-menu");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const setMenu = (open) => {
    if (!menuButton || !menu) return;
    menuButton.setAttribute("aria-expanded", String(open));
    menu.classList.toggle("open", open);
    document.body.classList.toggle("menu-open", open);
  };

  menuButton?.addEventListener("click", () => setMenu(menuButton.getAttribute("aria-expanded") !== "true"));
  menu?.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setMenu(false)));
  window.addEventListener("scroll", () => header?.classList.toggle("scrolled", window.scrollY > 12), { passive: true });

  const reveals = document.querySelectorAll(".reveal");
  if (reducedMotion.matches || !("IntersectionObserver" in window)) {
    reveals.forEach((node) => node.classList.add("visible"));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.16 });
    reveals.forEach((node) => observer.observe(node));
  }

  document.querySelectorAll("[data-spotlight]").forEach((card) => {
    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--mouse-x", `${event.clientX - rect.left}px`);
      card.style.setProperty("--mouse-y", `${event.clientY - rect.top}px`);
    });
  });

  if (!reducedMotion.matches) {
    const parallax = document.querySelector("[data-parallax]");
    window.addEventListener("scroll", () => {
      if (!parallax || window.innerWidth < 900) return;
      const progress = Math.min(window.scrollY / 650, 1);
      parallax.style.opacity = String(1 - progress * 0.38);
      parallax.style.transform = `translateY(${progress * 52}px) scale(${1 - progress * 0.035})`;
    }, { passive: true });
  }

  const compactHash = (hash) => hash ? `SHA-256 ${hash.slice(0, 10)}…${hash.slice(-8)}` : "发布链接由官网后台维护";
  const setRelease = (release) => {
    const title = document.getElementById("releaseTitle");
    const notes = document.getElementById("releaseNotes");
    const version = document.getElementById("releaseVersion");
    const checksum = document.getElementById("releaseChecksum");
    const download = document.getElementById("releaseDownload");
    if (title) title.textContent = release.title || `Video Mix Pro ${release.latest_version}`;
    if (notes) notes.textContent = release.notes || "最新稳定版已经准备好，可下载中文安装包覆盖升级。";
    if (version) version.textContent = `v${release.latest_version}`;
    if (checksum) checksum.textContent = compactHash(release.sha256 || "");
    document.querySelectorAll(".eyebrow-version").forEach((node) => { node.textContent = `v${release.latest_version}`; });
    if (release.download_url) {
      document.querySelectorAll(".download-link").forEach((link) => {
        link.href = release.download_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.classList.remove("disabled");
      });
    } else if (download) {
      download.classList.add("disabled");
      download.textContent = "即将发布";
      download.removeAttribute("href");
    }
  };

  fetch("/api/update/latest", { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(setRelease)
    .catch(() => {
      const notes = document.getElementById("releaseNotes");
      if (notes) notes.textContent = "暂时无法读取发布信息，请稍后刷新页面。";
    });

  fetch("/api/site/pricing", { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((payload) => {
      (payload.items || []).forEach((item) => {
        const card = document.querySelector(`[data-pricing-plan="${item.plan}"]`);
        const price = card?.querySelector("[data-price-value]");
        if (price) price.textContent = item.price_display || "后台配置";
      });
    })
    .catch(() => undefined);
})();
