const gallery = document.getElementById("gallery-grid");
const themeToggle = document.getElementById("theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const navLinks = document.querySelectorAll("nav a");
const sections = document.querySelectorAll(".view-section");
const albumPillsContainer = document.getElementById("album-pills");

let photos = [];
let albums = [];
let currentAlbumId = 0; // 0 = "All Work"

// Initialize
async function init() {
  await loadAlbums();
  await fetchPhotoList();
}

// Load albums
async function loadAlbums() {
  try {
    const response = await fetch("/api/albums");
    albums = await response.json();
    renderAlbumPills();
  } catch (error) {
    // Error loading albums
  }
}

// Render album filter pills
function renderAlbumPills() {
  albumPillsContainer.innerHTML = "";

  albums.forEach((album) => {
    const pill = document.createElement("button");
    pill.className = `pill ${currentAlbumId === album.id ? "active" : ""}`;
    pill.textContent = album.name;
    pill.onclick = () => filterByAlbum(album.id);
    albumPillsContainer.appendChild(pill);
  });
}

// Filter photos by album
async function filterByAlbum(albumId) {
  currentAlbumId = albumId;
  renderAlbumPills();
  await fetchPhotoList();
  window.scrollTo(0, 0);
}

// Fetch photo list from API
async function fetchPhotoList() {
  try {
    const url =
      currentAlbumId === 0
        ? "/api/photo_list"
        : `/api/photo_list?album_id=${currentAlbumId}`;
    const response = await fetch(url);
    photos = await response.json();
    loadImages();
  } catch (error) {
    // Error fetching photo list
  }
}

// Function to load images
function loadImages() {
  gallery.innerHTML = "";

  if (photos.length === 0) {
    gallery.innerHTML =
      '<div style="grid-column: 1/-1; text-align:center; color:var(--text-secondary); padding:40px;">No photos found.</div>';
    return;
  }

  photos.forEach((photo, index) => {
    const container = document.createElement("div");
    container.className = "gallery-item";

    const link = document.createElement("a");
    link.href = `/static/photos/${photo}`;
    link.setAttribute("data-fancybox", "gallery");

    const img = document.createElement("img");
    const src = `/static/photos/${photo}`;
    img.src = src.replace(".webp", "-thumbnail.webp");
    img.setAttribute("loading", "lazy");
    img.alt = `Photo ${index + 1}`;

    link.appendChild(img);
    container.appendChild(link);
    gallery.appendChild(container);
  });

  // Initialize Fancybox
  Fancybox.bind('[data-fancybox="gallery"]', {
    Toolbar: {
      display: {
        right: ["slideshow", "fullscreen", "thumbs", "close"],
      },
    },
  });
}

// Theme toggle
themeToggle.addEventListener("click", () => {
  document.body.classList.toggle("dark-mode");
  const isDark = document.body.classList.contains("dark-mode");
  themeIcon.className = isDark ? "ri-sun-line" : "ri-moon-line";

  // Save preference
  localStorage.setItem("theme", isDark ? "dark" : "light");
});

// Navigation
navLinks.forEach((link) => {
  link.addEventListener("click", (e) => {
    const targetSection = link.getAttribute("data-section");

    // If link doesn't have data-section attribute, let it navigate normally
    if (!targetSection) {
      return; // Allow default behavior (navigation to href)
    }

    e.preventDefault();

    // Update URL hash
    if (targetSection === "about") {
      window.location.hash = targetSection;
    } else {
      // Remove hash when clicking on Gallery
      history.pushState("", document.title, window.location.pathname);
    }

    switchSection(targetSection);
  });
});

// Function to switch sections
function switchSection(targetSection) {
  navLinks.forEach((l) => l.classList.remove("active"));
  document
    .querySelector(`[data-section="${targetSection}"]`)
    .classList.add("active");

  sections.forEach((section) => {
    if (section.id === `view-${targetSection}`) {
      section.classList.add("active-view");
    } else {
      section.classList.remove("active-view");
    }
  });

  // Scroll to top
  window.scrollTo(0, 0);
}

// Handle browser back/forward buttons
window.addEventListener("popstate", () => {
  const currentHash = window.location.hash.substring(1);
  const targetSection = currentHash || "gallery";
  switchSection(targetSection);
});

// Handle initial hash on page load
window.addEventListener("load", () => {
  const hash = window.location.hash.substring(1);
  const targetSection = hash === "about" ? "about" : "gallery";
  switchSection(targetSection);

  // Load saved theme preference
  const savedTheme = localStorage.getItem("theme");
  if (
    savedTheme === "dark" ||
    (!savedTheme && window.matchMedia("(prefers-color-scheme: dark)").matches)
  ) {
    document.body.classList.add("dark-mode");
    themeIcon.className = "ri-sun-line";
  }

  // Save current theme state if not already saved
  if (!savedTheme) {
    const isDark = document.body.classList.contains("dark-mode");
    localStorage.setItem("theme", isDark ? "dark" : "light");
  }
});

// Listen to system theme changes
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", (event) => {
    if (!localStorage.getItem("theme")) {
      document.body.classList.toggle("dark-mode", event.matches);
      themeIcon.className = event.matches ? "ri-sun-line" : "ri-moon-line";
    }
  });

// Initial load
init();
