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
    const startX = e.clientX;
    const startW = panelEl.offsetWidth;
    if (typeof handleEl.setPointerCapture === "function" && e.pointerId != null) {
      try {
        handleEl.setPointerCapture(e.pointerId);
      } catch {
        /* capture unsupported */
      }
    }
    const root = document.body || document.documentElement;
    const prevUserSelect = root && root.style ? root.style.userSelect : "";
    if (root && root.style) root.style.userSelect = "none";
    if (root && root.classList) root.classList.add("select-none", "is-resizing");
    const move = (ev) => {
      const w = computePanelWidth(startW, ev.clientX, startX, { min, max, side });
      panelEl.style.width = w + "px";
    };
    let done = false;
    const up = () => {
      if (done) return;
      done = true;
      lsSet(storageKey, String(panelEl.offsetWidth));
      if (root && root.style) root.style.userSelect = prevUserSelect;
      if (root && root.classList) root.classList.remove("select-none", "is-resizing");
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
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
