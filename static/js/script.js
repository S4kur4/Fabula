const gallery = document.getElementById("gallery-grid");
const themeToggle = document.getElementById("theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const navLinks = document.querySelectorAll("nav a");
const sections = document.querySelectorAll(".view-section");
const albumPillsContainer = document.getElementById("album-pills");

let photos = [];
let albums = [];
let currentAlbumId = 0; // 0 = "All Work"
let nextOffset = 0;
let hasMore = true;
let isLoading = false;
let loadedCount = 0;
let pendingReset = false;

const PAGE_SIZE = 24;
const sentinel = document.createElement("div");
sentinel.id = "gallery-sentinel";

// Initialize
async function init() {
  await loadAlbums();
  setupInfiniteScroll();
  await fetchPhotoList(true);
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
  await fetchPhotoList(true);
  window.scrollTo(0, 0);
}

function resetGallery() {
  gallery.innerHTML = "";
  photos = [];
  nextOffset = 0;
  hasMore = true;
  loadedCount = 0;
}

// Fetch photo list from API (paged)
async function fetchPhotoList(reset = false) {
  if (isLoading) {
    if (reset) pendingReset = true;
    return;
  }
  if (reset) {
    resetGallery();
  } else if (!hasMore) {
    return;
  }
  isLoading = true;

  try {
    const params = new URLSearchParams({
      limit: PAGE_SIZE,
      offset: nextOffset,
    });
    if (currentAlbumId !== 0) {
      params.append("album_id", currentAlbumId);
    }
    const url = `/api/photo_list?${params.toString()}`;
    const response = await fetch(url);
    const data = await response.json();
    const items = data.items || [];
    photos = photos.concat(items);
    appendImages(items);
    nextOffset = data.next_offset;
    hasMore = nextOffset !== null;
  } catch (error) {
    // Error fetching photo list
  } finally {
    isLoading = false;
    if (pendingReset) {
      pendingReset = false;
      fetchPhotoList(true);
    }
  }
}

function appendImages(items) {
  if (items.length === 0 && photos.length === 0) {
    gallery.innerHTML =
      '<div style="grid-column: 1/-1; text-align:center; color:var(--text-secondary); padding:40px;">No photos found.</div>';
    return;
  }

  items.forEach((photo) => {
    const container = document.createElement("div");
    container.className = "gallery-item";

    const link = document.createElement("a");
    link.href = `/static/photos/${photo}`;
    link.setAttribute("data-fancybox", "gallery");

    const img = document.createElement("img");
    const src = `/static/photos/${photo}`;
    img.src = src.replace(".webp", "-thumbnail.webp");
    img.setAttribute("loading", "lazy");
    loadedCount += 1;
    img.alt = `Photo ${loadedCount}`;

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

// Infinite scroll observer
function setupInfiniteScroll() {
  if (!sentinel.isConnected) {
    gallery.parentElement.appendChild(sentinel);
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          fetchPhotoList();
        }
      });
    },
    { rootMargin: "200px" }
  );

  observer.observe(sentinel);
}
