(() => {
  "use strict";

  const root = document.documentElement;
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = document.querySelector("#toast");
  let toastTimer = 0;

  function preferredTheme() {
    const stored = window.localStorage.getItem("fabula-theme");
    if (stored === "dark" || stored === "light") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.textContent = theme === "dark" ? "晨光" : "夜色";
      button.setAttribute("aria-pressed", String(theme === "dark"));
    });
  }

  function showToast(message, kind = "success") {
    if (!toast) {
      return;
    }
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.toggle("is-error", kind === "error");
    toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3600);
  }

  async function api(url, options = {}) {
    const requestOptions = {
      credentials: "same-origin",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    };
    const method = String(requestOptions.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      requestOptions.headers["X-CSRF-Token"] = csrfToken;
    }
    if (requestOptions.body && !(requestOptions.body instanceof FormData)) {
      requestOptions.headers["Content-Type"] = "application/json";
    }
    const response = await window.fetch(url, requestOptions);
    const payload = await response.json().catch(() => ({
      success: false,
      message: "服务器返回了无法识别的响应",
    }));
    if (!response.ok) {
      const error = new Error(payload.message || "请求未能完成");
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function closeDialog(dialog) {
    if (dialog?.open) {
      dialog.close();
    }
    if (!document.querySelector("dialog[open]")) {
      document.body.classList.remove("is-modal-open");
    }
  }

  function openDialog(dialog) {
    if (!dialog) {
      return;
    }
    dialog.showModal();
    document.body.classList.add("is-modal-open");
  }

  function noticeAfterReload(message, kind = "success", preserveScroll = true) {
    window.sessionStorage.setItem("fabula-notice", JSON.stringify({ message, kind }));
    if (preserveScroll) {
      window.sessionStorage.setItem("fabula-scroll-y", String(window.scrollY));
    }
  }

  applyTheme(preferredTheme());

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      window.localStorage.setItem("fabula-theme", nextTheme);
      applyTheme(nextTheme);
    });
  });

  document.addEventListener("click", (event) => {
    const closeButton = event.target.closest("[data-close-dialog]");
    if (!closeButton) {
      return;
    }
    closeDialog(document.getElementById(closeButton.dataset.closeDialog));
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        closeDialog(dialog);
      }
    });
    dialog.addEventListener("close", () => {
      if (!document.querySelector("dialog[open]")) {
        document.body.classList.remove("is-modal-open");
      }
    });
  });

  document.querySelectorAll("[data-flash-category]").forEach((message) => {
    showToast(
      message.textContent.trim(),
      message.dataset.flashCategory === "error" ? "error" : "success",
    );
  });

  const storedNotice = window.sessionStorage.getItem("fabula-notice");
  if (storedNotice) {
    window.sessionStorage.removeItem("fabula-notice");
    try {
      const notice = JSON.parse(storedNotice);
      showToast(notice.message, notice.kind);
    } catch {
      window.sessionStorage.removeItem("fabula-notice");
    }
  }

  const storedScrollValue = window.sessionStorage.getItem("fabula-scroll-y");
  if (storedScrollValue !== null) {
    window.sessionStorage.removeItem("fabula-scroll-y");
    const storedScroll = Number(storedScrollValue);
    if (Number.isFinite(storedScroll) && storedScroll > 0) {
      window.requestAnimationFrame(() => window.scrollTo({ top: storedScroll }));
    }
  }

  window.Fabula = {
    api,
    closeDialog,
    csrfToken,
    openDialog,
    noticeAfterReload,
    showToast,
  };
})();
