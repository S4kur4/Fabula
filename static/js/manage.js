// Theme management
const themeToggle = document.getElementById("theme-toggle");
const themeIcon = document.getElementById("theme-icon");

themeToggle.addEventListener("click", () => {
  document.body.classList.toggle("dark-mode");
  const isDark = document.body.classList.contains("dark-mode");
  themeIcon.className = isDark ? "ri-sun-line" : "ri-moon-line";
  localStorage.setItem("theme", isDark ? "dark" : "light");
});

// Load saved theme
const savedTheme = localStorage.getItem("theme");
if (
  savedTheme === "dark" ||
  (!savedTheme && window.matchMedia("(prefers-color-scheme: dark)").matches)
) {
  document.body.classList.add("dark-mode");
  themeIcon.className = "ri-sun-line";
}

// Global state
let albums = [];
let photos = [];
let nextOffset = 0;
let hasMore = true;
let isLoading = false;
const PAGE_SIZE = 24;
const sentinel = document.createElement("div");
sentinel.id = "photo-sentinel";
let refreshTimer = null;
let pendingReset = false;
let uploadAlbumId = "";
const selectedPhotos = new Set();
let restoreScrollY = null;
const locallyDeleted = new Set();
let totalCount = 0;
let islandTimer = null;
let islandMode = "hidden";
const ISLAND_MESSAGE_DURATION = 3000;
let islandHideToken = 0;

// Initialize
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  await loadAlbums();
  setupInfiniteScroll();
  setupEventStream();
  await loadPhotos(true);
  await loadAbout();
  setupFileUpload();
});

// Album Management
async function loadAlbums() {
  try {
    const response = await fetch("/api/albums");
    albums = await response.json();
    renderAlbums();
    renderUploadAlbumSelect();
  } catch (error) {
    // Error loading albums
  }
}

function renderAlbums() {
  const container = document.getElementById("album-list");
  container.innerHTML = "";

  albums.forEach((album) => {
    if (album.id === 0) return; // Skip "All Work"

    const card = document.createElement("div");
    card.className = "album-card";
    card.innerHTML = `
            <div>
                <div class="album-name">${album.name}</div>
                <div class="album-count">${album.photo_count || 0} items</div>
            </div>
            <div class="album-actions">
                <button class="icon-btn" onclick="renameAlbum(${album.id})" title="Rename">
                    <i class="ri-edit-line"></i>
                </button>
                <button class="icon-btn danger" onclick="deleteAlbum(${album.id})" title="Delete">
                    <i class="ri-delete-bin-line"></i>
                </button>
            </div>
        `;
    container.appendChild(card);
  });
}

function renderUploadAlbumSelect() {
  const select = document.getElementById("upload-album-select");
  const note = document.getElementById("upload-album-note");
  if (!select || !note) return;

  const previous = uploadAlbumId;
  select.innerHTML = "";

  const uncategorized = document.createElement("option");
  uncategorized.value = "";
  uncategorized.textContent = "Uncategorized";
  select.appendChild(uncategorized);

  albums.forEach((album) => {
    if (album.id === 0) return;
    const option = document.createElement("option");
    option.value = String(album.id);
    option.textContent = album.name;
    select.appendChild(option);
  });

  if (previous && albums.some((a) => String(a.id) === previous)) {
    select.value = previous;
  } else {
    select.value = "";
    uploadAlbumId = "";
  }

  const label =
    select.value === ""
      ? "Uncategorized"
      : albums.find((a) => String(a.id) === select.value)?.name || "Uncategorized";
  note.textContent = `Uploads will be added to: ${label}`;

  select.onchange = () => {
    uploadAlbumId = select.value;
    const name =
      uploadAlbumId === ""
        ? "Uncategorized"
        : albums.find((a) => String(a.id) === uploadAlbumId)?.name ||
          "Uncategorized";
    note.textContent = `Uploads will be added to: ${name}`;
  };
}

async function createNewAlbum() {
  const name = prompt("New Album Name:");
  if (!name) return;

  try {
    const response = await fetch("/api/albums", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums();
      await loadPhotos(true); // Reload to update selects
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to create album");
  }
}

async function renameAlbum(albumId) {
  const album = albums.find((a) => a.id === albumId);
  const newName = prompt("Rename Album:", album.name);
  if (!newName || newName === album.name) return;

  try {
    const response = await fetch(`/api/albums/${albumId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums();
      await loadPhotos(true);
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to rename album");
  }
}

async function deleteAlbum(albumId) {
  if (!confirm("Delete this album? Photos inside will become uncategorized."))
    return;

  const albumName = albums.find((a) => a.id === albumId)?.name || albumId;

  try {
    const response = await fetch(`/api/albums/${albumId}`, {
      method: "DELETE",
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums();
      await loadPhotos(true);
      showMessageIsland(`Album "${albumName}" has been deleted`, "album_deleted");
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to delete album");
  }
}

// Photo Management
function resetPhotos() {
  const container = document.getElementById("photo-grid");
  container.innerHTML = "";
  photos = [];
  nextOffset = 0;
  hasMore = true;
  selectedPhotos.clear();
  updateSelectionUI();
}

async function loadPhotos(reset = false) {
  if (isLoading) {
    if (reset) pendingReset = true;
    return;
  }
  if (reset) {
    resetPhotos();
  } else if (!hasMore) {
    return;
  }
  isLoading = true;
  const wasReset = reset;

  try {
    const params = new URLSearchParams({
      full_info: "true",
      include_processing: "true",
      limit: PAGE_SIZE,
      offset: nextOffset,
    });
    const response = await fetch(`/api/photo_list?${params.toString()}`);
    const data = await response.json();
    const items = data.items || [];
    photos = photos.concat(items);

    totalCount = data.total || 0;
    document.getElementById("photo-count").textContent =
      `${totalCount} items`;
    renderPhotos(items);
    nextOffset = data.next_offset;
    hasMore = nextOffset !== null;
  } catch (error) {
    // Error loading photos
  } finally {
    isLoading = false;
    if (wasReset && restoreScrollY !== null) {
      const y = restoreScrollY;
      restoreScrollY = null;
      requestAnimationFrame(() => window.scrollTo(0, y));
    }
    if (pendingReset) {
      pendingReset = false;
      loadPhotos(true);
    }
  }
}

function renderPhotos(items) {
  const container = document.getElementById("photo-grid");

  items.forEach((photo) => {
    const card = document.createElement("div");
    card.className = "manage-card";
    card.setAttribute("data-photo", photo.filename);

    const thumbnailName = photo.filename.replace(".webp", "-thumbnail.webp");
    const isReady = photo.status === "ready";
    const statusLabel =
      photo.status === "processing"
        ? "Processing..."
        : photo.status === "failed"
        ? "Failed"
        : "";

    // Build album options with correct selected state
    let optionsHtml = `<option value="" ${!photo.album_id ? "selected" : ""}>Uncategorized</option>`;
    albums.forEach((album) => {
      if (album.id !== 0) {
        const isSelected = photo.album_id === album.id ? "selected" : "";
        optionsHtml += `<option value="${album.id}" ${isSelected}>${album.name}</option>`;
      }
    });

    card.innerHTML = `
            <div class="manage-img-wrap">
                <input type="checkbox" class="select-checkbox" data-filename="${photo.filename}" ${
                  selectedPhotos.has(photo.filename) ? "checked" : ""
                } onchange="toggleSelection('${photo.filename}', this.checked)">
                ${
                  isReady
                    ? `<img src="/static/photos/${thumbnailName}" alt="${photo.filename}">`
                    : `<div class="processing-placeholder">${statusLabel}</div>`
                }
            </div>
            <div class="manage-body">
                <div class="file-name" title="${photo.filename}">${photo.filename}</div>
                <select class="album-select" onchange="updatePhotoAlbum('${photo.filename}', this.value)">
                    ${optionsHtml}
                </select>
                <div class="card-footer">
                    <span>${formatPhotoMeta(photo)}</span>
                    <span class="delete-text" onclick="deletePhoto('${photo.filename}')">
                        <i class="ri-delete-bin-line"></i> Delete
                    </span>
                </div>
            </div>
        `;

    container.appendChild(card);
  });

  updateSelectionUI();
  renderSelectionIsland();
}

async function updatePhotoAlbum(filename, albumId) {
  try {
    const response = await fetch(`/api/photos/${filename}/album`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ album_id: albumId || null }),
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums(); // Refresh counts
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to update photo album");
  }
}

async function deletePhoto(filename) {
  if (!confirm("Permanently delete this photo?")) return;

  try {
    restoreScrollY = window.scrollY;
    locallyDeleted.add(filename);
    const response = await fetch("/api/delete_photo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });

    const result = await response.json();
    if (result.success) {
      selectedPhotos.delete(filename);
      removePhotoFromUI(filename);
      showMessageIsland(`Photo "${filename}" has been deleted`, "photo_deleted");
      updateSelectionUI();
      await loadAlbums();
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to delete photo");
  }
}

// File Upload
function setupFileUpload() {
  const fileInput = document.getElementById("file-input");
  fileInput.addEventListener("change", (e) => {
    handleFileSelect(e.target.files);
  });
}

async function handleFileSelect(files) {
  if (!files || files.length === 0) return;

  const progressBar = document.getElementById("upload-progress");
  const progressFill = document.querySelector(".progress-fill");
  const progressCount = document.querySelector(".progress-count");
  const progressThumb = document.querySelector(".progress-thumbnail");

  progressBar.style.display = "";
  progressBar.classList.remove("is-hiding");
  requestAnimationFrame(() => {
    progressBar.classList.add("is-visible");
  });

  for (let i = 0; i < files.length; i++) {
    const file = files[i];

    // Create thumbnail preview
    const reader = new FileReader();
    reader.onload = (e) => {
      progressThumb.src = e.target.result;
    };
    reader.readAsDataURL(file);

    // Update progress count
    progressCount.textContent = `${i + 1}/${files.length}`;

    try {
      await uploadPhoto(file);
      progressFill.style.width = `${((i + 1) / files.length) * 100}%`;
    } catch (error) {
      // Error uploading file
    }
  }

  // Hide progress bar
  setTimeout(() => {
    progressBar.classList.remove("is-visible");
    progressBar.classList.add("is-hiding");
    const handler = () => {
      progressBar.style.display = "none";
      progressBar.classList.remove("is-hiding");
      progressBar.removeEventListener("transitionend", handler);
    };
    progressBar.addEventListener("transitionend", handler);
    progressFill.style.width = "0";
  }, 1000);

  // Reset file input
  document.getElementById("file-input").value = "";
}

async function uploadPhoto(file) {
  const formData = new FormData();
  formData.append("photo", file);
  if (uploadAlbumId) {
    formData.append("album_id", uploadAlbumId);
  }

  const response = await fetch("/api/upload_photo", {
    method: "POST",
    body: formData,
  });

  const result = await response.json();
  if (result.success) {
    restoreScrollY = window.scrollY;
    await loadAlbums();
    await loadPhotos(true);
  } else {
    alert("Failed to upload photo: " + result.message);
    throw new Error(result.message);
  }
}


function setupInfiniteScroll() {
  const container = document.getElementById("photo-grid");
  if (!sentinel.isConnected) {
    container.parentElement.appendChild(sentinel);
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          loadPhotos();
        }
      });
    },
    { rootMargin: "200px" }
  );

  observer.observe(sentinel);
}

function setupEventStream() {
  const source = new EventSource("/api/events");

  source.addEventListener("photo_status", (event) => {
    const payload = safeParseEvent(event);
    if (payload && payload.status === "ready") {
      scheduleRefresh();
    }
  });

  source.addEventListener("photo_deleted", (event) => {
    const payload = safeParseEvent(event);
    if (!payload || !payload.filename) return;
    if (locallyDeleted.has(payload.filename)) {
      locallyDeleted.delete(payload.filename);
      return;
    }
    removePhotoFromUI(payload.filename);
  });

  source.onerror = () => {
    // Let the browser handle automatic reconnect
  };
}

function scheduleRefresh() {
  if (refreshTimer) return;
  if (restoreScrollY === null) {
    restoreScrollY = window.scrollY;
  }
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    await loadAlbums();
    await loadPhotos(true);
  }, 500);
}

function safeParseEvent(event) {
  try {
    return JSON.parse(event.data || "{}");
  } catch (error) {
    return null;
  }
}

function toggleSelection(filename, checked) {
  if (checked) {
    selectedPhotos.add(filename);
  } else {
    selectedPhotos.delete(filename);
  }
  updateSelectionUI();
}

function selectAllVisible() {
  photos.forEach((photo) => {
    selectedPhotos.add(photo.filename);
  });
  updateSelectionUI();
}

function clearSelection() {
  selectedPhotos.clear();
  updateSelectionUI();
}

function renderSelectionIsland() {
  if (islandMode === "message") return;
  if (selectedPhotos.size === 0) {
    hideIsland();
    return;
  }

  const inner = document.getElementById("action-island-inner");
  if (!inner) return;

  islandMode = "selection";
  inner.innerHTML = `
    <div class="action-left">
      <span>${selectedPhotos.size} selected</span>
      <button class="btn-ghost" onclick="selectAllVisible()">Select All</button>
      <button class="btn-ghost" onclick="clearSelection()">Clear</button>
    </div>
    <button class="btn-danger" onclick="deleteSelected()">
      <i class="ri-delete-bin-line"></i> Delete Selected
    </button>
  `;

  showIsland();
}

function showMessageIsland(message, type = "info") {
  const inner = document.getElementById("action-island-inner");
  if (!inner) return;
  islandMode = "message";
  const icon = getIslandIcon(type);
  inner.innerHTML = `
    <div class="action-message">
      <i class="${icon} action-icon"></i>
      <span>${message}</span>
    </div>
  `;
  showIsland(ISLAND_MESSAGE_DURATION);
}

function showIsland(autoHideMs = null) {
  const island = document.getElementById("action-island");
  if (!island) return;

  islandHideToken += 1;

  if (islandTimer) {
    clearTimeout(islandTimer);
    islandTimer = null;
  }

  island.style.display = "";
  island.classList.remove("is-hiding");
  requestAnimationFrame(() => {
    island.classList.add("is-visible");
  });

  if (autoHideMs) {
    islandTimer = setTimeout(() => {
      hideIsland();
    }, autoHideMs);
  }
}

function hideIsland() {
  const island = document.getElementById("action-island");
  if (!island) return;

  const token = islandHideToken;

  island.classList.remove("is-visible");
  island.classList.add("is-hiding");
  const handler = () => {
    if (token !== islandHideToken) {
      island.removeEventListener("transitionend", handler);
      return;
    }
    island.style.display = "none";
    island.classList.remove("is-hiding");
    island.removeEventListener("transitionend", handler);
    islandMode = selectedPhotos.size > 0 ? "selection" : "hidden";
    if (islandMode === "selection") {
      renderSelectionIsland();
    }
  };
  island.addEventListener("transitionend", handler);
}

function getIslandIcon(type) {
  switch (type) {
    case "photo_deleted":
      return "ri-image-2-line";
    case "album_deleted":
      return "ri-folder-2-line";
    case "bulk_deleted":
      return "ri-delete-bin-6-line";
    default:
      return "ri-notification-3-line";
  }
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / Math.pow(1024, index);
  const precision = value < 10 && index > 0 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "Unknown date";
  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function formatPhotoMeta(photo) {
  const size = formatBytes(photo.size_bytes);
  const date = formatDate(photo.created_at);
  return `${size} • ${date}`;
}

function updateSelectionUI() {
  const checkboxes = document.querySelectorAll(".select-checkbox");
  checkboxes.forEach((cb) => {
    const filename = cb.getAttribute("data-filename");
    if (filename) {
      cb.checked = selectedPhotos.has(filename);
    }
  });

  renderSelectionIsland();
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".tab-panel");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.getAttribute("data-tab");
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      panels.forEach((panel) => {
        panel.classList.toggle(
          "active",
          panel.getAttribute("data-panel") === target
        );
      });
      window.scrollTo(0, 0);
    });
  });
}

async function loadAbout() {
  try {
    const response = await fetch("/api/about");
    const data = await response.json();

    document.getElementById("about-heading").value = data.heading || "";
    document.getElementById("about-me").value = data.me || "";
    document.getElementById("about-signature").value = data.signature || "";

    const gearList = document.getElementById("gear-list");
    const contactList = document.getElementById("contact-list");
    gearList.innerHTML = "";
    contactList.innerHTML = "";

    (data.gear || []).forEach((item) => addGearRow(item.category, item.item));
    (data.contact || []).forEach((item) =>
      addContactRow(item.platform, item.handle)
    );

    if ((data.gear || []).length === 0) addGearRow();
    if ((data.contact || []).length === 0) addContactRow();
  } catch (error) {
    // Failed to load About
  }
}

function addGearRow(category = "", item = "") {
  const list = document.getElementById("gear-list");
  const row = document.createElement("div");
  row.className = "row-item";
  row.innerHTML = `
    <input type="text" placeholder="Category" value="${category}">
    <input type="text" placeholder="Item" value="${item}">
    <button class="btn-ghost" type="button">Remove</button>
  `;
  row.querySelector("button").onclick = () => row.remove();
  list.appendChild(row);
}

function addContactRow(platform = "", handle = "") {
  const list = document.getElementById("contact-list");
  const row = document.createElement("div");
  row.className = "row-item";
  row.innerHTML = `
    <input type="text" placeholder="Platform" value="${platform}">
    <input type="text" placeholder="Handle" value="${handle}">
    <button class="btn-ghost" type="button">Remove</button>
  `;
  row.querySelector("button").onclick = () => row.remove();
  list.appendChild(row);
}

async function saveAbout() {
  const gear = Array.from(document.querySelectorAll("#gear-list .row-item")).map(
    (row) => {
      const inputs = row.querySelectorAll("input");
      return {
        category: inputs[0].value.trim(),
        item: inputs[1].value.trim(),
      };
    }
  ).filter((g) => g.category || g.item);

  const contact = Array.from(
    document.querySelectorAll("#contact-list .row-item")
  ).map((row) => {
    const inputs = row.querySelectorAll("input");
    return {
      platform: inputs[0].value.trim(),
      handle: inputs[1].value.trim(),
    };
  }).filter((c) => c.platform || c.handle);

  const payload = {
    heading: document.getElementById("about-heading").value.trim(),
    me: document.getElementById("about-me").value.trim(),
    signature: document.getElementById("about-signature").value.trim(),
    gear,
    contact,
  };

  try {
    const response = await fetch("/api/about", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (result.success) {
      showMessageIsland("About updated", "info");
    } else {
      alert(result.message || "Failed to update About");
    }
  } catch (error) {
    alert("Failed to update About");
  }
}

async function deleteSelected() {
  if (selectedPhotos.size === 0) return;
  if (!confirm(`Delete ${selectedPhotos.size} selected photos?`)) return;

  const filenames = Array.from(selectedPhotos);
  try {
    restoreScrollY = window.scrollY;
    filenames.forEach((name) => locallyDeleted.add(name));
    const response = await fetch("/api/delete_photos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filenames }),
    });

    const result = await response.json();
    if (result.success) {
      filenames.forEach((name) => removePhotoFromUI(name));
      selectedPhotos.clear();
      showMessageIsland(`Deleted ${filenames.length} photos`, "bulk_deleted");
      updateSelectionUI();
      await loadAlbums();
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to delete photos");
  }
}

function removePhotoFromUI(filename) {
  const index = photos.findIndex((p) => p.filename === filename);
  if (index !== -1) {
    photos.splice(index, 1);
    totalCount = Math.max(0, totalCount - 1);
    document.getElementById("photo-count").textContent =
      `${totalCount} items`;
  }

  const container = document.getElementById("photo-grid");
  const card = container.querySelector(`[data-photo="${filename}"]`);
  if (card) card.remove();
}

// Logout
function logout() {
  if (confirm("Are you sure you want to logout?")) {
    window.location.href = "/logout";
  }
}
