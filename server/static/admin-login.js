(() => {
  const form = document.getElementById("loginForm");
  const button = document.getElementById("loginButton");
  const message = document.getElementById("loginMessage");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    if (!username || !password) {
      message.textContent = "请输入账号和密码";
      return;
    }
    button.disabled = true;
    button.textContent = "正在登录…";
    message.textContent = "";
    try {
      const response = await fetch("/admin/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) throw new Error(await response.text() || "登录失败");
      window.location.reload();
    } catch (error) {
      message.textContent = error instanceof Error ? error.message : "登录失败";
      button.disabled = false;
      button.textContent = "安全登录";
    }
  });
})();
