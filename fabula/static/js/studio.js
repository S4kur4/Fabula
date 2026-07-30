(() => {
  "use strict";

  const app = document.querySelector("#studio-app");
  if (!app) {
    return;
  }

  const currentUserId = Number(app.dataset.userId);
  const isAdmin = app.dataset.role === "admin";
  const albumDialog = document.querySelector("#album-dialog");
  const deleteAlbumDialog = document.querySelector("#delete-album-dialog");
  const photoDialog = document.querySelector("#photo-dialog");
  const userDialog = document.querySelector("#user-dialog");
  const resetDialog = document.querySelector("#reset-password-dialog");
  const t = window.Fabula.t;
  const selected = new Set();
  let albumFilter = "all";
  let users = [];
  let uploadPreviewUrl = "";

  document.querySelector("#logout-form")?.addEventListener("submit", (event) => {
    if (!window.confirm(t("退出当前工作台并返回公开首页？"))) {
      event.preventDefault();
    }
  });

  function errorText(target, message = "") {
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.toggle("is-visible", Boolean(message));
  }

  function jsonBody(values) {
    return JSON.stringify(values);
  }

  function showTab(name, updateUrl = true) {
    const tab = document.querySelector(`[data-studio-tab="${name}"]`);
    const panel = document.querySelector(`[data-studio-panel="${name}"]`);
    if (!panel) {
      return;
    }
    document.querySelectorAll("[data-studio-tab]").forEach((button) => {
      const active = Boolean(tab) && button.dataset.studioTab === name;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    if (name !== "photos") {
      document.querySelectorAll("[data-owned-album]").forEach((button) => {
        button.classList.remove("is-active");
      });
    }
    document.querySelectorAll("[data-studio-panel]").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.studioPanel === name);
    });
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", name);
      if (name !== "photos") {
        url.searchParams.delete("album");
      }
      window.history.replaceState(null, "", url);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    if (name === "users" && isAdmin) {
      loadUsers();
    }
  }

  document.querySelectorAll("[data-studio-tab]").forEach((button) => {
    button.addEventListener("click", () => showTab(button.dataset.studioTab));
  });

  function rowMatchesAlbum(row, value) {
    const rowAlbum = row.dataset.albumId || "";
    return value === "all" || (value === "uncategorized" ? rowAlbum === "" : rowAlbum === value);
  }

  function albumButton(value) {
    return [...document.querySelectorAll("[data-owned-album]")]
      .find((button) => button.dataset.ownedAlbum === String(value));
  }

  function photosUrl(value = albumFilter) {
    const url = new URL("/studio", window.location.origin);
    url.searchParams.set("tab", "photos");
    if (value !== "all") {
      url.searchParams.set("album", value);
    }
    return `${url.pathname}${url.search}`;
  }

  function applyAlbumFilter(value, updateUrl = true) {
    const activeButton = albumButton(value) || albumButton("all");
    if (!activeButton) {
      return;
    }
    albumFilter = activeButton.dataset.ownedAlbum;
    showTab("photos", false);
    document.querySelectorAll("[data-owned-album]").forEach((button) => {
      button.classList.toggle("is-active", button === activeButton);
    });
    document.querySelectorAll("[data-managed-photo]").forEach((row) => {
      row.hidden = !rowMatchesAlbum(row, albumFilter);
    });
    clearSelection();

    const albumName = activeButton.dataset.albumName || t("全部照片");
    const photoCount = Number(activeButton.dataset.albumPhotoCount || 0);
    const isSelectedAlbum = albumFilter !== "all" && albumFilter !== "uncategorized";
    const actionMode = isSelectedAlbum
      ? "selected"
      : albumFilter === "uncategorized" ? "uncategorized" : "general";
    document.querySelectorAll("[data-album-actions]").forEach((group) => {
      group.hidden = group.dataset.albumActions !== actionMode;
    });

    const title = document.querySelector("#photo-panel-title");
    const description = document.querySelector("#photo-panel-description");
    if (albumFilter === "all") {
      title.textContent = t("全部照片");
      description.textContent = t("这里汇总你拥有的全部照片。其他摄影师的内容不会出现在你的工作台中。");
    } else if (albumFilter === "uncategorized") {
      title.textContent = t("未分类");
      description.textContent = t(
        "这里有 {count} 张尚未归入摄影集的照片。你可以批量选择或直接上传新照片。",
        { count: photoCount },
      );
    } else {
      title.textContent = albumName;
      description.textContent = t(
        "这里只显示“{name}”中的 {count} 张照片，右侧操作均只作用于本摄影集。",
        { name: albumName, count: photoCount },
      );
    }

    const uploadAlbum = document.querySelector("#upload-album");
    const uploadTarget = uploadAlbum?.closest(".upload-target");
    const uploadTitle = document.querySelector("#upload-title");
    if (uploadAlbum) {
      uploadAlbum.value = isSelectedAlbum ? albumFilter : "";
      uploadAlbum.disabled = albumFilter !== "all";
      uploadTarget?.classList.toggle("is-locked", albumFilter !== "all");
    }
    if (uploadTitle) {
      uploadTitle.textContent = isSelectedAlbum
        ? t("上传到“{name}”", { name: albumName })
        : albumFilter === "uncategorized" ? t("上传未分类照片") : t("加入你的摄影集");
    }

    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", "photos");
      if (albumFilter === "all") {
        url.searchParams.delete("album");
      } else {
        url.searchParams.set("album", albumFilter);
      }
      window.history.replaceState(null, "", url);
    }
  }

  document.querySelectorAll("[data-owned-album]").forEach((button) => {
    button.addEventListener("click", () => {
      applyAlbumFilter(button.dataset.ownedAlbum);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  const initialTab = app.dataset.activeTab || "photos";
  showTab(initialTab, false);
  if (initialTab === "photos") {
    applyAlbumFilter(new URL(window.location.href).searchParams.get("album") || "all", false);
  }

  function openAlbumEditor(id = "", name = "") {
    document.querySelector("#editing-album-id").value = id;
    document.querySelector("#album-name").value = name;
    document.querySelector("#album-dialog-title").textContent = id
      ? t("重命名摄影集")
      : t("新建摄影集");
    errorText(document.querySelector("#album-error"));
    window.Fabula.openDialog(albumDialog);
    window.setTimeout(() => document.querySelector("#album-name").focus(), 0);
  }

  document.querySelector("[data-open-album]")?.addEventListener("click", () => openAlbumEditor());

  document.querySelector("[data-context-rename-album]")?.addEventListener("click", () => {
    const button = albumButton(albumFilter);
    if (button && albumFilter !== "all" && albumFilter !== "uncategorized") {
      openAlbumEditor(albumFilter, button.dataset.albumName);
    }
  });

  document.querySelector("[data-context-delete-album]")?.addEventListener("click", () => {
    const button = albumButton(albumFilter);
    if (!button || albumFilter === "all" || albumFilter === "uncategorized") {
      return;
    }
    const photoCount = Number(button.dataset.albumPhotoCount || 0);
    document.querySelector("#delete-album-id").value = albumFilter;
    document.querySelector("#delete-album-name").textContent = button.dataset.albumName;
    document.querySelector("#delete-album-impact").textContent =
      t("同步删除本摄影集中的 {count} 张照片，此操作无法恢复。", {
        count: photoCount,
      });
    document.querySelector('input[name="delete-album-mode"][value="keep"]').checked = true;
    errorText(document.querySelector("#delete-album-error"));
    window.Fabula.openDialog(deleteAlbumDialog);
  });

  document.querySelector("#delete-album-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.querySelector("#delete-album-id").value;
    const deletePhotos = document.querySelector('input[name="delete-album-mode"]:checked')?.value === "delete";
    try {
      const payload = await window.Fabula.api(`/studio/api/albums/${id}`, {
        method: "DELETE",
        body: jsonBody({ delete_photos: deletePhotos }),
      });
      window.Fabula.closeDialog(deleteAlbumDialog);
      window.Fabula.noticeAfterReload(payload.message, "success", false);
      window.location.assign(photosUrl("all"));
    } catch (error) {
      errorText(document.querySelector("#delete-album-error"), error.message);
    }
  });

  document.querySelector("#album-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.querySelector("#editing-album-id").value;
    const name = document.querySelector("#album-name").value.trim();
    const endpoint = id ? `/studio/api/albums/${id}` : "/studio/api/albums";
    try {
      const payload = await window.Fabula.api(endpoint, {
        method: id ? "PATCH" : "POST",
        body: jsonBody({ name }),
      });
      window.Fabula.closeDialog(albumDialog);
      window.Fabula.noticeAfterReload(
        id ? t("摄影集已重命名") : t("摄影集已创建"),
        "success",
        false,
      );
      window.location.assign(photosUrl(id || payload.album.id));
    } catch (error) {
      errorText(document.querySelector("#album-error"), error.message);
    }
  });

  const fileInput = document.querySelector("#photo-upload");

  async function uploadFiles(files) {
    if (!files.length) {
      return;
    }
    const status = document.querySelector("#upload-status");
    const statusText = document.querySelector("#upload-status-text");
    const progress = document.querySelector("#upload-progress");
    const albumId = document.querySelector("#upload-album").value;
    status.hidden = false;
    let succeeded = 0;
    for (let index = 0; index < files.length; index += 1) {
      const formData = new FormData();
      formData.append("photo", files[index]);
      if (albumId) {
        formData.append("album_id", albumId);
      }
      if (uploadPreviewUrl) {
        URL.revokeObjectURL(uploadPreviewUrl);
      }
      uploadPreviewUrl = URL.createObjectURL(files[index]);
      const preview = document.querySelector("#upload-preview");
      preview.src = uploadPreviewUrl;
      preview.hidden = false;
      statusText.textContent = t("正在处理 {current} / {total}: {name}", {
        current: index + 1,
        total: files.length,
        name: files[index].name,
      });
      progress.value = Math.round((index / files.length) * 100);
      try {
        await window.Fabula.api("/studio/api/photos", {
          method: "POST",
          body: formData,
        });
        succeeded += 1;
      } catch (error) {
        window.Fabula.showToast(`${files[index].name}: ${error.message}`, "error");
      }
      progress.value = Math.round(((index + 1) / files.length) * 100);
    }
    statusText.textContent = t("完成 {current} / {total}", {
      current: succeeded,
      total: files.length,
    });
    if (succeeded) {
      window.Fabula.noticeAfterReload(
        t("{count} 张照片已加入你的档案", { count: succeeded }),
        "success",
        false,
      );
      window.setTimeout(() => window.location.assign(photosUrl()), 600);
    }
  }

  fileInput?.addEventListener("change", () => {
    uploadFiles([...fileInput.files]);
    fileInput.value = "";
  });

  function rowData(row) {
    const data = row.querySelector(".photo-data");
    return {
      id: Number(row.dataset.managedPhoto),
      title: data?.dataset.title || "",
      story: data?.dataset.story || "",
      album_id: data?.dataset.album || "",
      thumb_url: data?.dataset.thumb || "",
    };
  }

  function makeManagedPhotoRow(photo) {
    const row = document.createElement("article");
    const checkbox = document.createElement("input");
    const core = document.createElement("div");
    const image = photo.thumb_url ? document.createElement("img") : document.createElement("div");
    const copy = document.createElement("div");
    const title = document.createElement("h3");
    const story = document.createElement("p");
    const fileMeta = document.createElement("small");
    const albumSelect = document.createElement("select");
    const status = document.createElement("span");
    const edit = document.createElement("button");
    const data = document.createElement("div");

    row.className = "manage-photo";
    row.dataset.managedPhoto = String(photo.id);
    row.dataset.albumId = photo.album_id === null ? "" : String(photo.album_id);
    row.hidden = !rowMatchesAlbum(row, albumFilter);

    checkbox.className = "select-box";
    checkbox.type = "checkbox";
    checkbox.dataset.selectPhoto = String(photo.id);
    checkbox.setAttribute(
      "aria-label",
      t("选择《{title}》", { title: photo.title || t("未命名照片") }),
    );

    core.className = "manage-photo-core";
    if (photo.thumb_url) {
      image.src = photo.thumb_url;
      image.alt = "";
    } else {
      image.className = "processing-image";
      image.textContent = {
        processing: t("处理中"),
        failed: t("处理失败"),
      }[photo.status] || t("等待处理");
    }
    title.textContent = photo.title || t("未命名照片");
    story.textContent = photo.story || t("尚未添加故事背景。");
    fileMeta.className = "photo-file-meta";
    fileMeta.textContent = `${photo.original_name} / ${Math.round(photo.size_bytes / 1024)} KB / ${photo.created_at.slice(0, 10)}`;
    copy.append(title, story, fileMeta);
    core.append(image, copy);

    albumSelect.className = "inline-select";
    albumSelect.dataset.photoAlbum = String(photo.id);
    albumSelect.setAttribute("aria-label", t("调整照片所属摄影集"));
    document.querySelectorAll("#upload-album option").forEach((sourceOption) => {
      const option = document.createElement("option");
      option.value = sourceOption.value;
      option.textContent = sourceOption.textContent;
      option.selected = option.value === (photo.album_id === null ? "" : String(photo.album_id));
      albumSelect.append(option);
    });

    status.className = "status-text";
    status.textContent = {
      ready: t("已发布"),
      processing: t("处理中"),
      failed: t("处理失败"),
    }[photo.status] || t("未知状态");
    edit.className = "row-action";
    edit.type = "button";
    edit.dataset.photoEdit = String(photo.id);
    edit.textContent = t("编辑或删除");
    data.className = "photo-data";
    data.hidden = true;
    data.dataset.title = photo.title || "";
    data.dataset.story = photo.story || "";
    data.dataset.album = photo.album_id === null ? "" : String(photo.album_id);
    data.dataset.thumb = photo.thumb_url || "";
    row.append(checkbox, core, albumSelect, status, edit, data);
    return row;
  }

  async function loadMoreManagedPhotos() {
    const button = document.querySelector("#studio-load-more");
    if (!button || button.disabled) {
      return;
    }
    button.disabled = true;
    button.textContent = t("正在加载");
    try {
      const offset = Number(button.dataset.offset || 0);
      const payload = await window.Fabula.api(`/studio/api/photos?limit=24&offset=${offset}`);
      const list = document.querySelector("#manage-photo-list");
      payload.items.forEach((photo) => list.append(makeManagedPhotoRow(photo)));
      if (payload.next_offset === null) {
        button.remove();
      } else {
        button.dataset.offset = String(payload.next_offset);
        button.disabled = false;
        button.textContent = t("加载更多");
      }
    } catch (error) {
      button.disabled = false;
      button.textContent = t("重新加载");
      window.Fabula.showToast(error.message, "error");
    }
  }

  const studioLoadMore = document.querySelector("#studio-load-more");
  studioLoadMore?.addEventListener("click", loadMoreManagedPhotos);
  if (studioLoadMore) {
    const loadObserver = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMoreManagedPhotos();
        }
      },
      { rootMargin: "500px 0px" },
    );
    loadObserver.observe(studioLoadMore);
  }

  async function checkPhotoRevision() {
    const photoPanel = document.querySelector('[data-studio-panel="photos"].is-active');
    if (!photoPanel || document.hidden || document.querySelector("dialog[open]")) {
      return;
    }
    try {
      const payload = await window.Fabula.api("/studio/api/revision");
      if (payload.photo_revision !== app.dataset.photoRevision) {
        window.Fabula.noticeAfterReload(t("全部照片已在另一个会话中更新"));
        window.location.assign(photosUrl());
      }
    } catch {
      return;
    }
  }

  if (document.querySelector('[data-studio-panel="photos"]') && !document.querySelector(".forced-password-notice")) {
    window.setInterval(checkPhotoRevision, 30000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        checkPhotoRevision();
      }
    });
  }

  function openPhotoEditor(row) {
    const photo = rowData(row);
    document.querySelector("#editing-photo-id").value = String(photo.id);
    document.querySelector("#photo-title").value = photo.title;
    document.querySelector("#photo-story").value = photo.story;
    document.querySelector("#photo-album").value = photo.album_id;
    document.querySelector("#photo-dialog-image").src = photo.thumb_url;
    errorText(document.querySelector("#photo-error"));
    window.Fabula.openDialog(photoDialog);
  }

  document.querySelector("#manage-photo-list")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-photo-edit]");
    if (button) {
      openPhotoEditor(button.closest("[data-managed-photo]"));
    }
  });

  async function updatePhoto(id, values) {
    return window.Fabula.api(`/studio/api/photos/${id}`, {
      method: "PATCH",
      body: jsonBody(values),
    });
  }

  document.querySelector("#manage-photo-list")?.addEventListener("change", async (event) => {
    const select = event.target.closest("[data-photo-album]");
    if (!select) {
      return;
    }
    const row = select.closest("[data-managed-photo]");
    const photo = rowData(row);
    try {
      await updatePhoto(photo.id, {
        title: photo.title,
        story: photo.story,
        album_id: select.value,
      });
      row.dataset.albumId = select.value;
      row.querySelector(".photo-data").dataset.album = select.value;
      window.Fabula.noticeAfterReload(t("照片已重新归类"));
      window.location.assign(photosUrl());
    } catch (error) {
      select.value = photo.album_id;
      window.Fabula.showToast(error.message, "error");
    }
  });

  document.querySelector("#photo-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.querySelector("#editing-photo-id").value;
    try {
      const payload = await updatePhoto(id, {
        title: document.querySelector("#photo-title").value,
        story: document.querySelector("#photo-story").value,
        album_id: document.querySelector("#photo-album").value,
      });
      window.Fabula.closeDialog(photoDialog);
      window.Fabula.noticeAfterReload(payload.message);
      window.location.assign(photosUrl());
    } catch (error) {
      errorText(document.querySelector("#photo-error"), error.message);
    }
  });

  async function deletePhoto(id) {
    const confirmed = window.confirm(
      t("删除这张照片和它的故事？此操作无法在工作台中撤销。"),
    );
    if (!confirmed) {
      return;
    }
    try {
      const payload = await window.Fabula.api(`/studio/api/photos/${id}`, { method: "DELETE" });
      window.Fabula.closeDialog(photoDialog);
      window.Fabula.noticeAfterReload(payload.message);
      window.location.assign(photosUrl());
    } catch (error) {
      errorText(document.querySelector("#photo-error"), error.message);
    }
  }

  document.querySelector("[data-delete-current-photo]")?.addEventListener("click", () => {
    deletePhoto(document.querySelector("#editing-photo-id").value);
  });

  function updateSelection() {
    const bar = document.querySelector("#bulk-bar");
    if (!bar) {
      return;
    }
    bar.hidden = selected.size === 0;
    document.querySelector("#selected-count").textContent = String(selected.size);
  }

  function clearSelection() {
    selected.clear();
    document.querySelectorAll("[data-select-photo]").forEach((checkbox) => {
      checkbox.checked = false;
    });
    updateSelection();
  }

  document.querySelector("#manage-photo-list")?.addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-select-photo]");
    if (!checkbox) {
      return;
    }
    const id = Number(checkbox.dataset.selectPhoto);
    if (checkbox.checked) {
      selected.add(id);
    } else {
      selected.delete(id);
    }
    updateSelection();
  });

  document.querySelector("[data-select-visible]")?.addEventListener("click", () => {
    document.querySelectorAll("[data-managed-photo]:not([hidden]) [data-select-photo]").forEach((checkbox) => {
      checkbox.checked = true;
      selected.add(Number(checkbox.dataset.selectPhoto));
    });
    updateSelection();
  });

  document.querySelectorAll("[data-context-select-photos]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-managed-photo]:not([hidden]) [data-select-photo]").forEach((checkbox) => {
        checkbox.checked = true;
        selected.add(Number(checkbox.dataset.selectPhoto));
      });
      updateSelection();
      document.querySelector("#manage-photo-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  document.querySelector("[data-clear-selection]")?.addEventListener("click", clearSelection);
  document.querySelector("[data-bulk-delete]")?.addEventListener("click", async () => {
    if (
      !selected.size
      || !window.confirm(t("删除已选择的 {count} 张照片？", { count: selected.size }))
    ) {
      return;
    }
    try {
      const payload = await window.Fabula.api("/studio/api/photos/bulk-delete", {
        method: "POST",
        body: jsonBody({ ids: [...selected] }),
      });
      window.Fabula.noticeAfterReload(
        t("{count} 张照片已删除", { count: payload.deleted }),
      );
      window.location.assign(photosUrl());
    } catch (error) {
      window.Fabula.showToast(error.message, "error");
    }
  });

  function listFromTextarea(selector) {
    return document.querySelector(selector).value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  document.querySelector("#about-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = await window.Fabula.api("/studio/api/about", {
        method: "PUT",
        body: jsonBody({
          display_name: document.querySelector("#about-display-name").value,
          title: document.querySelector("#about-title").value,
          bio: document.querySelector("#about-bio").value,
          signature: document.querySelector("#about-signature").value,
          gear: listFromTextarea("#about-gear"),
          contact: listFromTextarea("#about-contact"),
        }),
      });
      document.querySelector("#about-preview-name").textContent = document.querySelector("#about-display-name").value;
      document.querySelector("#about-preview-title").textContent = document.querySelector("#about-title").value;
      errorText(document.querySelector("#about-error"));
      window.Fabula.showToast(payload.message);
    } catch (error) {
      errorText(document.querySelector("#about-error"), error.message);
    }
  });

  document.querySelector("#security-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = await window.Fabula.api("/studio/api/account/password", {
        method: "POST",
        body: jsonBody({
          current_password: document.querySelector("#current-password").value,
          new_password: document.querySelector("#new-password").value,
          confirmation: document.querySelector("#confirm-password").value,
        }),
      });
      errorText(document.querySelector("#security-error"));
      window.Fabula.showToast(payload.message);
      window.setTimeout(() => window.location.assign("/studio"), 500);
    } catch (error) {
      errorText(document.querySelector("#security-error"), error.message);
    }
  });

  const copyFields = [
    "site-title",
    "hero-before",
    "hero-accent",
    "hero-after",
    "hero-note",
    "hero-cta",
    "archive-title",
    "archive-intro",
    "about-title",
    "about-intro",
    "login-title",
    "login-intro",
  ];

  function siteCopyValues() {
    const values = Object.fromEntries(copyFields.map((name) => [
      name.replaceAll("-", "_"),
      document.querySelector(`#copy-${name}`).value,
    ]));
    values.color_scheme = document.querySelector(
      'input[name="site-color-scheme"]:checked',
    )?.value || document.documentElement.dataset.palette;
    return values;
  }

  function updateCopyPreview() {
    const mappings = {
      "#copy-preview-site-title": "#copy-site-title",
      "#copy-preview-before": "#copy-hero-before",
      "#copy-preview-accent": "#copy-hero-accent",
      "#copy-preview-after": "#copy-hero-after",
      "#copy-preview-note": "#copy-hero-note",
    };
    Object.entries(mappings).forEach(([previewSelector, fieldSelector]) => {
      const preview = document.querySelector(previewSelector);
      const field = document.querySelector(fieldSelector);
      if (preview && field) {
        preview.textContent = field.value;
      }
    });
  }

  copyFields.forEach((name) => document.querySelector(`#copy-${name}`)?.addEventListener("input", updateCopyPreview));
  document.querySelectorAll('input[name="site-color-scheme"]').forEach((input) => {
    input.addEventListener("change", () => {
      document.documentElement.dataset.palette = input.value;
    });
  });
  document.querySelector("#site-copy-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = await window.Fabula.api("/api/admin/site-copy", {
        method: "PUT",
        body: jsonBody(siteCopyValues()),
      });
      errorText(document.querySelector("#site-copy-error"));
      const siteTitle = document.querySelector("#copy-site-title").value.trim();
      document.querySelector(".studio-brand strong").textContent = siteTitle;
      document.title = `${t("工作台")} | ${siteTitle}`;
      document.documentElement.dataset.palette = payload.site_copy.color_scheme;
      window.Fabula.showToast(t("站点设置已保存"));
    } catch (error) {
      errorText(document.querySelector("#site-copy-error"), error.message);
    }
  });

  function makeUserRow(user) {
    const row = document.createElement("div");
    const name = document.createElement("span");
    const username = document.createElement("span");
    const role = document.createElement("span");
    const status = document.createElement("span");
    const content = document.createElement("span");
    const actions = document.createElement("span");
    const strong = document.createElement("strong");
    const note = document.createElement("small");
    row.className = "user-row";
    row.setAttribute("role", "row");
    row.dataset.userRow = String(user.id);
    strong.textContent = user.display_name;
    note.textContent = user.id === currentUserId
      ? t("当前账号")
      : user.must_change_password ? t("等待修改临时密码") : "";
    name.append(strong, note);
    username.textContent = user.username;
    role.className = "user-role";
    role.textContent = user.role === "admin" ? t("管理员") : t("摄影师");
    status.className = "user-status";
    status.dataset.status = user.status;
    status.textContent = {
      active: t("有效"),
      inactive: t("已停用"),
      pending: t("待启用"),
    }[user.status] || user.status;
    content.textContent = t("{photos} 照片 / {albums} 摄影集", {
      photos: user.content.photos,
      albums: user.content.albums,
    });
    actions.className = "user-actions";
    const actionSpecs = [
      [t("编辑"), "edit"],
      [user.status === "inactive" ? t("启用") : t("停用"), "status"],
      [t("重置密码"), "reset"],
      [t("删除"), "delete"],
    ];
    actionSpecs.forEach(([label, action]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.userAction = action;
      button.dataset.userId = String(user.id);
      if (user.id === currentUserId && ["status", "reset", "delete"].includes(action)) {
        button.disabled = true;
      }
      actions.append(button);
    });
    row.append(name, username, role, status, content, actions);
    return row;
  }

  async function loadUsers() {
    const list = document.querySelector("#user-list");
    if (!list) {
      return;
    }
    try {
      const payload = await window.Fabula.api("/api/admin/users");
      users = payload.items;
      list.replaceChildren(...users.map(makeUserRow));
    } catch (error) {
      list.textContent = error.message;
      window.Fabula.showToast(error.message, "error");
    }
  }

  function openUserEditor(user = null) {
    document.querySelector("#editing-user-id").value = user ? String(user.id) : "";
    document.querySelector("#user-dialog-title").textContent = user
      ? t("编辑用户")
      : t("创建用户");
    document.querySelector("#user-username").value = user?.username || "";
    document.querySelector("#user-username").disabled = Boolean(user);
    document.querySelector("#user-display-name").value = user?.display_name || "";
    document.querySelector("#user-role").value = user?.role || "photographer";
    document.querySelector("#temporary-password-field").hidden = Boolean(user);
    document.querySelector("#user-temporary-password").value = "welcome-2026";
    errorText(document.querySelector("#user-error"));
    window.Fabula.openDialog(userDialog);
  }

  document.querySelector("[data-open-user]")?.addEventListener("click", () => openUserEditor());

  document.querySelector("#user-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.querySelector("#editing-user-id").value;
    const values = {
      username: document.querySelector("#user-username").value,
      display_name: document.querySelector("#user-display-name").value,
      role: document.querySelector("#user-role").value,
      temporary_password: document.querySelector("#user-temporary-password").value,
    };
    try {
      await window.Fabula.api(id ? `/api/admin/users/${id}` : "/api/admin/users", {
        method: id ? "PATCH" : "POST",
        body: jsonBody(values),
      });
      window.Fabula.closeDialog(userDialog);
      window.Fabula.showToast(id ? t("用户资料已更新") : t("用户已创建"));
      if (Number(id) === currentUserId && values.role !== "admin") {
        window.location.assign("/studio");
        return;
      }
      loadUsers();
    } catch (error) {
      errorText(document.querySelector("#user-error"), error.message);
    }
  });

  document.querySelector("#user-list")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-user-action]");
    if (!button) {
      return;
    }
    const user = users.find((item) => item.id === Number(button.dataset.userId));
    if (!user) {
      return;
    }
    if (button.dataset.userAction === "edit") {
      openUserEditor(user);
      return;
    }
    if (button.dataset.userAction === "reset") {
      document.querySelector("#reset-user-id").value = String(user.id);
      document.querySelector("#reset-password-impact").textContent = t(
        "将撤销 {name} 的现有会话，并要求下次登录时修改密码。",
        { name: user.display_name },
      );
      document.querySelector("#reset-temporary-password").value = "temporary-2026";
      errorText(document.querySelector("#reset-password-error"));
      window.Fabula.openDialog(resetDialog);
      return;
    }
    if (button.dataset.userAction === "status") {
      const status = user.status === "inactive" ? "active" : "inactive";
      const action = status === "inactive" ? t("停用") : t("启用");
      if (!window.confirm(t("{action}用户“{name}”？", { action, name: user.display_name }))) {
        return;
      }
      try {
        await window.Fabula.api(`/api/admin/users/${user.id}/status`, {
          method: "POST",
          body: jsonBody({ status }),
        });
        window.Fabula.showToast(
          status === "inactive"
            ? t("用户已停用，现有会话已撤销")
            : t("用户已启用"),
        );
        loadUsers();
      } catch (error) {
        window.Fabula.showToast(error.message, "error");
      }
      return;
    }
    if (button.dataset.userAction === "delete") {
      if (
        !window.confirm(
          t("永久删除空账号“{name}”？拥有内容的用户不会被允许删除。", {
            name: user.display_name,
          }),
        )
      ) {
        return;
      }
      try {
        const payload = await window.Fabula.api(`/api/admin/users/${user.id}`, { method: "DELETE" });
        window.Fabula.showToast(payload.message);
        loadUsers();
      } catch (error) {
        window.Fabula.showToast(error.message, "error");
      }
    }
  });

  document.querySelector("#reset-password-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.querySelector("#reset-user-id").value;
    try {
      const payload = await window.Fabula.api(`/api/admin/users/${id}/reset-password`, {
        method: "POST",
        body: jsonBody({ temporary_password: document.querySelector("#reset-temporary-password").value }),
      });
      window.Fabula.closeDialog(resetDialog);
      window.Fabula.showToast(payload.message);
      loadUsers();
    } catch (error) {
      errorText(document.querySelector("#reset-password-error"), error.message);
    }
  });

  if (isAdmin && app.dataset.activeTab === "users") {
    loadUsers();
  }
})();
