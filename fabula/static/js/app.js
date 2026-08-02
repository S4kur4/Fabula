(() => {
  "use strict";

  const root = document.documentElement;
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = document.querySelector("#toast");
  const catalogElement = document.querySelector("#fabula-i18n");
  let catalog = {};
  let toastTimer = 0;

  try {
    catalog = JSON.parse(catalogElement?.textContent || "{}");
  } catch {
    catalog = {};
  }

  function t(message, values = {}) {
    const translated = catalog[message] || message;
    return Object.entries(values).reduce(
      (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
      translated,
    );
  }

  function storageGet(storageName, key) {
    try {
      return window[storageName].getItem(key);
    } catch {
      return null;
    }
  }

  function storageSet(storageName, key, value) {
    try {
      window[storageName].setItem(key, value);
    } catch {
      // Storage can be disabled by privacy controls; the UI still works in memory.
    }
  }

  function storageRemove(storageName, key) {
    try {
      window[storageName].removeItem(key);
    } catch {
      // Ignore unavailable browser storage.
    }
  }

  function preferredTheme() {
    const stored = storageGet("localStorage", "fabula-theme");
    if (stored === "dark" || stored === "light") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.textContent = theme === "dark" ? t("晨光") : t("夜色");
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
    let response;
    try {
      response = await window.fetch(url, requestOptions);
    } catch {
      throw new Error(t("无法连接服务器，请检查网络后重试"));
    }
    const fallbackMessage = response.status === 413
      ? t("图片超过上传大小限制")
      : response.status >= 500
        ? t("服务器暂时无法处理请求，请稍后重试")
        : t("服务器返回了无法识别的响应（HTTP {status}）", { status: response.status });
    const payload = await response.json().catch(() => ({
      success: false,
      message: fallbackMessage,
    }));
    if (!response.ok) {
      const error = new Error(payload.message || t("请求未能完成"));
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
    storageSet("sessionStorage", "fabula-notice", JSON.stringify({ message, kind }));
    if (preserveScroll) {
      storageSet("sessionStorage", "fabula-scroll-y", String(window.scrollY));
    }
  }

  applyTheme(preferredTheme());

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      storageSet("localStorage", "fabula-theme", nextTheme);
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

  const storedNotice = storageGet("sessionStorage", "fabula-notice");
  if (storedNotice) {
    storageRemove("sessionStorage", "fabula-notice");
    try {
      const notice = JSON.parse(storedNotice);
      showToast(notice.message, notice.kind);
    } catch {
      storageRemove("sessionStorage", "fabula-notice");
    }
  }

  const storedScrollValue = storageGet("sessionStorage", "fabula-scroll-y");
  if (storedScrollValue !== null) {
    storageRemove("sessionStorage", "fabula-scroll-y");
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
    t,
  };
})();
