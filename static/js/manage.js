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

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  loadAlbums();
  loadPhotos();
  setupFileUpload();
});

// Album Management
async function loadAlbums() {
  try {
    const response = await fetch("/api/albums");
    albums = await response.json();
    renderAlbums();
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
      await loadPhotos(); // Reload to update selects
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
      await loadPhotos();
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

  try {
    const response = await fetch(`/api/albums/${albumId}`, {
      method: "DELETE",
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums();
      await loadPhotos();
    } else {
      alert(result.message);
    }
  } catch (error) {
    alert("Failed to delete album");
  }
}

// Photo Management
async function loadPhotos() {
  try {
    const response = await fetch("/api/photo_list?full_info=true");
    photos = await response.json();

    document.getElementById("photo-count").textContent =
      `${photos.length} items`;
    renderPhotos();
  } catch (error) {
    // Error loading photos
  }
}

function renderPhotos() {
  const container = document.getElementById("photo-grid");
  container.innerHTML = "";

  photos.forEach((photo) => {
    const card = document.createElement("div");
    card.className = "manage-card";

    const thumbnailName = photo.filename.replace(".webp", "-thumbnail.webp");

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
                <img src="/static/photos/${thumbnailName}" alt="${photo.filename}">
            </div>
            <div class="manage-body">
                <div class="file-name" title="${photo.filename}">${photo.filename}</div>
                <select class="album-select" onchange="updatePhotoAlbum('${photo.filename}', this.value)">
                    ${optionsHtml}
                </select>
                <div class="card-footer">
                    <span>${photo.filename.substring(0, 8)}...</span>
                    <span class="delete-text" onclick="deletePhoto('${photo.filename}')">
                        <i class="ri-delete-bin-line"></i> Delete
                    </span>
                </div>
            </div>
        `;

    container.appendChild(card);
  });
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
    const response = await fetch("/api/delete_photo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });

    const result = await response.json();
    if (result.success) {
      await loadAlbums();
      await loadPhotos();
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
    progressBar.style.display = "none";
    progressFill.style.width = "0";
  }, 1000);

  // Reset file input
  document.getElementById("file-input").value = "";
}

async function uploadPhoto(file) {
  const formData = new FormData();
  formData.append("photo", file);

  const response = await fetch("/api/upload_photo", {
    method: "POST",
    body: formData,
  });

  const result = await response.json();
  if (result.success) {
    await loadAlbums();
    await loadPhotos();
  } else {
    alert("Failed to upload photo: " + result.message);
    throw new Error(result.message);
  }
}

// Logout
function logout() {
  if (confirm("Are you sure you want to logout?")) {
    window.location.href = "/logout";
  }
}
