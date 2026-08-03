(() => {
  "use strict";

  const galleryGrid = document.querySelector("#gallery-grid");
  const sentinel = document.querySelector("#gallery-sentinel");
  const galleryError = document.querySelector("#gallery-error");
  const lightbox = document.querySelector("#lightbox");
  const lightboxImage = document.querySelector("#lightbox-image");
  const lightboxTitle = document.querySelector("#lightbox-title");
  const lightboxStory = document.querySelector("#lightbox-story");
  const lightboxMeta = document.querySelector("#lightbox-meta");
  const lightboxThumbs = document.querySelector("#lightbox-thumbs");
  const t = window.Fabula.t;
  let activeAlbum = "";
  let nextOffset = sentinel?.dataset.nextOffset || "";
  let loading = false;
  let lightboxIndex = 0;
  let slideshowTimer = 0;
  let photoModels = [];

  function showPublicView(name, updateHash = true) {
    const safeName = name === "about" ? "about" : "gallery";
    document.querySelectorAll("[data-public-page]").forEach((view) => {
      view.classList.toggle("is-active", view.dataset.publicPage === safeName);
    });
    document.querySelectorAll("[data-public-view]").forEach((link) => {
      const active = link.dataset.publicView === safeName;
      link.classList.toggle("is-active", active);
      if (active) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
    if (updateHash && window.location.hash !== `#${safeName}`) {
      window.history.pushState(null, "", `#${safeName}`);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelectorAll("[data-public-view]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      showPublicView(link.dataset.publicView);
    });
  });

  window.addEventListener("popstate", () => {
    showPublicView(window.location.hash.slice(1), false);
  });

  if (window.location.hash === "#about") {
    showPublicView("about", false);
  }

  const revealObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: "0px 0px -7% 0px", threshold: 0.08 },
  );

  function observeReveals(scope = document) {
    scope.querySelectorAll(".reveal:not(.is-visible)").forEach((item) => revealObserver.observe(item));
  }

  function photoFromCard(card) {
    return {
      id: Number(card.dataset.photoId),
      title: card.dataset.photoTitle || "",
      photographer: card.dataset.photoPhotographer || "",
      album: card.dataset.photoAlbum || t("未分类"),
      image_url: card.dataset.photoImage || "",
      thumb_url: card.querySelector("img")?.src || "",
      story: card.querySelector(".photo-story-data")?.textContent.trim() || "",
    };
  }

  function currentPhotos() {
    return photoModels;
  }

  photoModels = [...document.querySelectorAll(".photo-card")].map(photoFromCard);

  function renderLightbox() {
    const photos = currentPhotos();
    if (!photos.length) {
      return;
    }
    lightboxIndex = (lightboxIndex + photos.length) % photos.length;
    const photo = photos[lightboxIndex];
    lightboxImage.src = photo.image_url;
    lightboxImage.alt = t("{title}，摄影师 {photographer}", {
      title: photo.title || t("摄影作品"),
      photographer: photo.photographer,
    });
    lightboxTitle.textContent = photo.title;
    lightboxStory.textContent = photo.story;
    lightboxTitle.hidden = !photo.title;
    lightboxStory.hidden = !photo.story;
    lightboxMeta.textContent = t(
      "{photographer} / {album} / 第 {index} 张，共 {total} 张",
      {
        photographer: photo.photographer,
        album: photo.album,
        index: lightboxIndex + 1,
        total: photos.length,
      },
    );
    if (lightboxThumbs.children.length !== photos.length) {
      lightboxThumbs.replaceChildren();
      photos.forEach((item, index) => {
        const button = document.createElement("button");
        const image = document.createElement("img");
        button.type = "button";
        button.setAttribute("aria-label", t("查看第 {index} 张照片", { index: index + 1 }));
        image.src = item.thumb_url;
        image.alt = "";
        image.draggable = false;
        button.append(image);
        button.addEventListener("click", () => {
          lightboxIndex = index;
          renderLightbox();
        });
        lightboxThumbs.append(button);
      });
    }
    [...lightboxThumbs.children].forEach((button, index) => {
      button.classList.toggle("is-active", index === lightboxIndex);
    });
  }

  function openPhoto(card) {
    const cards = [...document.querySelectorAll(".photo-card")];
    lightboxIndex = Math.max(0, cards.indexOf(card));
    renderLightbox();
    window.Fabula.openDialog(lightbox);
  }

  galleryGrid?.addEventListener("click", (event) => {
    const card = event.target.closest(".photo-card");
    if (card && event.target.closest(".photo-open")) {
      openPhoto(card);
    }
  });

  document.querySelectorAll("[data-lightbox-move]").forEach((button) => {
    button.addEventListener("click", () => {
      lightboxIndex += Number(button.dataset.lightboxMove);
      renderLightbox();
    });
  });

  document.querySelector("[data-lightbox-slideshow]")?.addEventListener("click", (event) => {
    if (slideshowTimer) {
      window.clearInterval(slideshowTimer);
      slideshowTimer = 0;
      event.currentTarget.textContent = t("播放");
      return;
    }
    event.currentTarget.textContent = t("暂停");
    slideshowTimer = window.setInterval(() => {
      lightboxIndex += 1;
      renderLightbox();
    }, 4500);
  });

  document.querySelector("[data-lightbox-thumbnails]")?.addEventListener("click", (event) => {
    lightboxThumbs.hidden = !lightboxThumbs.hidden;
    event.currentTarget.setAttribute("aria-pressed", String(!lightboxThumbs.hidden));
    event.currentTarget.textContent = lightboxThumbs.hidden
      ? t("显示缩略图")
      : t("隐藏缩略图");
  });

  lightbox?.addEventListener("close", () => {
    if (slideshowTimer) {
      window.clearInterval(slideshowTimer);
      slideshowTimer = 0;
      document.querySelector("[data-lightbox-slideshow]").textContent = t("播放");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (!lightbox?.open) {
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      lightboxIndex += event.key === "ArrowLeft" ? -1 : 1;
      renderLightbox();
    }
  });

  function makePhotoCard(photo) {
    const card = document.createElement("article");
    const openButton = document.createElement("button");
    const image = document.createElement("img");
    const caption = document.createElement("div");
    const title = document.createElement("h3");
    const meta = document.createElement("p");
    const story = document.createElement("p");
    card.className = `photo-card reveal ${photo.height > photo.width ? "is-portrait" : "is-landscape"}`;
    card.dataset.photoId = String(photo.id);
    card.dataset.photoTitle = photo.title || "";
    card.dataset.photoPhotographer = photo.photographer;
    card.dataset.photoAlbum = photo.album;
    card.dataset.photoImage = photo.image_url;
    openButton.className = "photo-open";
    openButton.type = "button";
    openButton.setAttribute(
      "aria-label",
      photo.title
        ? t("打开《{title}》的照片故事", { title: photo.title })
        : t("打开 {photographer} 的照片故事", { photographer: photo.photographer }),
    );
    image.src = photo.thumb_url;
    image.alt = t("{title}，摄影师 {photographer}", {
      title: photo.title || t("摄影作品"),
      photographer: photo.photographer,
    });
    image.loading = "lazy";
    image.draggable = false;
    image.width = photo.width;
    image.height = photo.height;
    caption.className = "photo-caption";
    if (!photo.title) {
      caption.classList.add("is-untitled");
    }
    title.textContent = photo.title || "";
    meta.append(document.createTextNode(photo.photographer), document.createElement("br"), document.createTextNode(photo.album));
    story.className = "photo-story-data";
    story.hidden = true;
    story.textContent = photo.story || "";
    openButton.append(image);
    if (photo.title) {
      caption.append(title);
    }
    caption.append(meta);
    card.append(openButton, caption, story);
    return card;
  }

  async function loadPhotos(reset = false) {
    if (loading || (!reset && nextOffset === "")) {
      return;
    }
    loading = true;
    galleryError.hidden = true;
    const offset = reset ? 0 : Number(nextOffset);
    const query = new URLSearchParams({ limit: "24", offset: String(offset) });
    if (activeAlbum) {
      query.set("album_id", activeAlbum);
    }
    try {
      const payload = await window.Fabula.api(`/api/public/photos?${query}`);
      if (reset) {
        galleryGrid.replaceChildren();
        photoModels = [];
      }
      payload.items.forEach((photo) => {
        photoModels.push(photo);
        galleryGrid.append(makePhotoCard(photo));
      });
      lightboxThumbs.replaceChildren();
      nextOffset = payload.next_offset === null ? "" : String(payload.next_offset);
      sentinel.dataset.nextOffset = nextOffset;
      if (!payload.items.length) {
        const empty = document.createElement("div");
        const heading = document.createElement("h3");
        const note = document.createElement("p");
        empty.className = "empty-state";
        heading.textContent = t("这个摄影集还是空的");
        note.textContent = t("上传作品后，它们会出现在这里。");
        empty.append(heading, note);
        galleryGrid.append(empty);
      }
      observeReveals(galleryGrid);
    } catch (error) {
      galleryError.hidden = false;
      window.Fabula.showToast(error.message, "error");
    } finally {
      loading = false;
    }
  }

  document.querySelectorAll("[data-album-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      activeAlbum = button.dataset.albumFilter;
      document.querySelectorAll("[data-album-filter]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      nextOffset = "0";
      loadPhotos(true);
      document.querySelector("#archive")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  document.querySelector("[data-gallery-retry]")?.addEventListener("click", () => loadPhotos(false));

  if (sentinel) {
    const feedObserver = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadPhotos(false);
        }
      },
      { rootMargin: "700px 0px" },
    );
    feedObserver.observe(sentinel);
  }

  observeReveals();
})();
