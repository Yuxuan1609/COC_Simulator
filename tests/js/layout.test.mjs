import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { computePanelWidth, initSplitter } from "../../frontend/static/js/layout.js";

function mockLocalStorage(seed = {}) {
  const store = { ...seed };
  globalThis.localStorage = {
    getItem(k) {
      return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
    },
    setItem(k, v) {
      store[k] = String(v);
    },
    removeItem(k) {
      delete store[k];
    },
    _store: store,
  };
}

beforeEach(() => {
  mockLocalStorage();
});

test("left panel: drag +40 widens 256 → 296", () => {
  assert.equal(computePanelWidth(256, 140, 100, { side: "left" }), 296);
});

test("left panel: clamps to min 200", () => {
  assert.equal(computePanelWidth(256, 0, 100, { min: 200, max: 800, side: "left" }), 200);
});

test("left panel: clamps to max 800", () => {
  assert.equal(computePanelWidth(256, 1100, 100, { min: 200, max: 800, side: "left" }), 800);
});

test("right panel: drag +40 (mouse right) narrows 384 → 344", () => {
  assert.equal(computePanelWidth(384, 140, 100, { side: "right" }), 344);
});

test("right panel: drag -40 widens 384 → 424", () => {
  assert.equal(computePanelWidth(384, 60, 100, { side: "right" }), 424);
});

test("right panel: clamps to min 200 and max 800", () => {
  assert.equal(computePanelWidth(384, 500, 100, { min: 200, max: 800, side: "right" }), 200);
  assert.equal(computePanelWidth(384, 0, 500, { min: 200, max: 800, side: "right" }), 800);
});

test("initSplitter restores saved width without touching offsetWidth", () => {
  mockLocalStorage({ trpg_panel_scene_w: "320" });
  const panel = { style: {}, offsetWidth: 0 };
  const handle = { addEventListener() {} };
  initSplitter(handle, panel, "trpg_panel_scene_w");
  assert.equal(panel.style.width, "320px");
});

test("initSplitter ignores pointermove from a different pointerId", () => {
  const docListeners = {};
  globalThis.document = {
    addEventListener(type, fn) {
      (docListeners[type] ||= []).push(fn);
    },
    removeEventListener(type, fn) {
      docListeners[type] = (docListeners[type] || []).filter((f) => f !== fn);
    },
    body: { style: {}, classList: { add() {}, remove() {} } },
  };
  const handleListeners = {};
  let captured = null;
  const panel = { style: {}, offsetWidth: 256 };
  const handle = {
    addEventListener(type, fn) {
      handleListeners[type] = fn;
    },
    removeEventListener() {},
    setPointerCapture(id) {
      captured = id;
    },
    hasPointerCapture(id) {
      return captured === id;
    },
    releasePointerCapture(id) {
      if (captured === id) captured = null;
    },
  };
  initSplitter(handle, panel, "k", { side: "left" });
  handleListeners.pointerdown({
    button: 0,
    clientX: 100,
    pointerId: 1,
    preventDefault() {},
  });
  for (const fn of docListeners.pointermove || []) {
    fn({ clientX: 140, pointerId: 2 });
  }
  assert.equal(panel.style.width, undefined);
  for (const fn of docListeners.pointermove || []) {
    fn({ clientX: 140, pointerId: 1 });
  }
  assert.equal(panel.style.width, "296px");
});
