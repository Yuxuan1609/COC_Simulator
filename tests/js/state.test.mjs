import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

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

test("state.debug reads trpg_debug", async () => {
  mockLocalStorage({ trpg_debug: "1" });
  const { loadState } = await import("../../frontend/static/js/state.js?debug=1");
  const s = loadState();
  assert.equal(s.debug, true);
});

test("state.autoWin reads trpg_autowin", async () => {
  mockLocalStorage({ trpg_autowin: "1" });
  const { loadState } = await import("../../frontend/static/js/state.js?autowin=1");
  const s = loadState();
  assert.equal(s.autoWin, true);
});

test("setSwitch persists into switches key", async () => {
  const { loadState, setSwitch } = await import("../../frontend/static/js/state.js?switch=1");
  const s = loadState();
  setSwitch("layout", "wide");
  assert.equal(s.switches.layout, "wide");
  assert.equal(JSON.parse(localStorage.getItem("switches")).layout, "wide");
});

test("setSwitch debug writes trpg_debug=1, not DEBUG", async () => {
  const { loadState, setSwitch } = await import("../../frontend/static/js/state.js?switch-debug=1");
  loadState();
  setSwitch("debug", true);
  assert.equal(localStorage.getItem("trpg_debug"), "1");
  assert.equal(localStorage.getItem("DEBUG"), null);
  assert.equal(localStorage.getItem("switches"), null);
});

test("setSwitch debug false removes trpg_debug", async () => {
  mockLocalStorage({ trpg_debug: "1" });
  const { loadState, setSwitch } = await import("../../frontend/static/js/state.js?switch-debug-off=1");
  const s = loadState();
  assert.equal(s.debug, true);
  setSwitch("debug", false);
  assert.equal(s.debug, false);
  assert.equal(localStorage.getItem("trpg_debug"), null);
  assert.equal(localStorage.getItem("DEBUG"), null);
});

test("setSwitch autoWin writes trpg_autowin, not switches", async () => {
  const { loadState, setSwitch } = await import("../../frontend/static/js/state.js?switch-autowin=1");
  const s = loadState();
  setSwitch("autoWin", true);
  assert.equal(s.autoWin, true);
  assert.equal(localStorage.getItem("trpg_autowin"), "1");
  assert.equal(localStorage.getItem("switches"), null);
});
