/** Panel splitter + switch paint. No bundler; imported as ES module. */

export function computePanelWidth(
  startW,
  clientX,
  startX,
  { min = 200, max = 800, side = "left" } = {},
) {
  const sign = side === "left" ? 1 : -1;
  return Math.min(max, Math.max(min, startW + sign * (clientX - startX)));
}

function lsGet(key) {
  try {
    if (typeof localStorage === "undefined") return null;
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function lsSet(key, val) {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(key, val);
  } catch {
    /* ignore quota / private mode */
  }
}

export function paintSwitch(el, on) {
  if (!el) return;
  const checked = !!on;
  el.classList.toggle("is-on", checked);
  el.setAttribute("aria-checked", checked ? "true" : "false");
}

export function initSplitter(
  handleEl,
  panelEl,
  storageKey,
  { min = 200, max = 800, side = "left" } = {},
) {
  if (!handleEl || !panelEl) return;
  const saved = lsGet(storageKey);
  if (saved != null && saved !== "") {
    const n = Number(saved);
    if (Number.isFinite(n)) {
      panelEl.style.width = Math.min(max, Math.max(min, n)) + "px";
    }
  }
  handleEl.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    const pointerId = e.pointerId;
    const startX = e.clientX;
    const startW = panelEl.offsetWidth;
    if (typeof handleEl.setPointerCapture === "function" && pointerId != null) {
      try {
        handleEl.setPointerCapture(pointerId);
      } catch {
        /* capture unsupported */
      }
    }
    const root = document.body || document.documentElement;
    const prevUserSelect = root && root.style ? root.style.userSelect : "";
    if (root && root.style) root.style.userSelect = "none";
    if (root && root.classList) root.classList.add("select-none", "is-resizing");
    const samePointer = (ev) =>
      pointerId == null || ev.pointerId == null || ev.pointerId === pointerId;
    const move = (ev) => {
      if (!samePointer(ev)) return;
      const w = computePanelWidth(startW, ev.clientX, startX, { min, max, side });
      panelEl.style.width = w + "px";
    };
    let done = false;
    const up = (ev) => {
      if (ev && !samePointer(ev)) return;
      if (done) return;
      done = true;
      lsSet(storageKey, String(panelEl.offsetWidth));
      if (root && root.style) root.style.userSelect = prevUserSelect;
      if (root && root.classList) root.classList.remove("select-none", "is-resizing");
      if (typeof handleEl.releasePointerCapture === "function" && pointerId != null) {
        try {
          const still =
            typeof handleEl.hasPointerCapture !== "function" ||
            handleEl.hasPointerCapture(pointerId);
          if (still) handleEl.releasePointerCapture(pointerId);
        } catch {
          /* already released */
        }
      }
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      handleEl.removeEventListener("lostpointercapture", up);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
    handleEl.addEventListener("lostpointercapture", up);
  });
}

export function initLayout() {
  const scenePanel = document.getElementById("scene-panel");
  if (scenePanel) {
    const handle = scenePanel.querySelector(".splitter");
    if (handle) {
      initSplitter(handle, scenePanel, "trpg_panel_scene_w", {
        min: 200,
        max: 800,
        side: "left",
      });
    }
  }
  const charPanel = document.getElementById("char-panel");
  if (charPanel) {
    const handle = charPanel.querySelector(".splitter");
    if (handle) {
      initSplitter(handle, charPanel, "trpg_panel_char_w", {
        min: 200,
        max: 800,
        side: "right",
      });
    }
  }
}
