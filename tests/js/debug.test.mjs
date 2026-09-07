import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  renderTrace,
  renderEntities,
  renderSkills,
  renderLlm,
  toggleDebug,
  syncDebugUi,
} from "../../frontend/static/js/debug.js";
import { state, loadState } from "../../frontend/static/js/state.js";

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

function el(initHidden) {
  const classes = new Set(initHidden ? ["hidden"] : []);
  const attrs = {};
  return {
    classList: {
      contains(c) { return classes.has(c); },
      add(c) { classes.add(c); },
      remove(c) { classes.delete(c); },
      toggle(c, force) {
        if (force === true) classes.add(c);
        else if (force === false) classes.delete(c);
        else if (classes.has(c)) classes.delete(c);
        else classes.add(c);
      },
    },
    innerHTML: "",
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    _attrs: attrs,
    _classes: classes,
  };
}

const origFetch = globalThis.fetch;
const origDoc = globalThis.document;
const origLoc = globalThis.location;

beforeEach(() => {
  mockLocalStorage();
});

afterEach(() => {
  globalThis.fetch = origFetch;
  if (origDoc === undefined) delete globalThis.document;
  else globalThis.document = origDoc;
  if (origLoc === undefined) delete globalThis.location;
  else globalThis.location = origLoc;
});

test("renderTrace escapes id/gate/reason XSS", () => {
  const html = renderTrace({
    evaluated: [{
      id: "<img src=x onerror=alert(1)>",
      available: false,
      gate: "<b>g</b>",
      reason: "<script>x</script>",
    }],
    matched: [{
      id: "<svg onload=alert(1)>",
      success: true,
      reason: '"onclick',
    }],
  });
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("<svg"), false);
  assert.equal(html.includes("<b>g</b>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
  assert.equal(html.includes("&lt;svg"), true);
  assert.equal(html.includes("&lt;b&gt;"), true);
});

test("renderTrace empty state", () => {
  assert.match(renderTrace(null), /本回合无流水（未开 debug 或尚未行动）/);
  assert.match(renderTrace({}), /本回合无流水（未开 debug 或尚未行动）/);
  assert.match(renderTrace({ evaluated: [], matched: [] }), /本回合无流水（未开 debug 或尚未行动）/);
});

test("renderEntities escapes id/name/reason XSS", () => {
  const html = renderEntities([{
    id: "<img src=x>",
    name: "<b>门</b>",
    available: false,
    gate: "requirement",
    reason: "<script>x</script>",
  }]);
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<b>门</b>"), false);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;b&gt;"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
});

test("renderEntities empty state", () => {
  assert.match(renderEntities([]), /暂无实体可用性数据/);
  assert.match(renderEntities(null), /暂无实体可用性数据/);
});

test("renderSkills escapes entity_id and empty state", () => {
  const html = renderSkills([{
    entity_id: "<img src=x>",
    tier: "<b>hard</b>",
    success: false,
    raw_roll: 90,
    target: 50,
  }]);
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<b>hard</b>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("D100=90/50"), true);
  assert.match(renderSkills([]), /本回合无检定/);
});

test("renderLlm escapes filename and preview", () => {
  const html = renderLlm([{
    filename: "<img src=x>.txt",
    preview: "<script>alert(1)</script>",
  }]);
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
  assert.match(renderLlm([]), /暂无 LLM 记录/);
});

test("toggleDebug does not reload and shows/hides panel", async () => {
  mockLocalStorage();
  loadState();
  let reloaded = false;
  globalThis.location = { reload() { reloaded = true; }, search: "" };
  const els = {};
  globalThis.document = {
    getElementById(id) {
      if (!els[id]) {
        els[id] = el(id === "debug-panel" || id === "debug-badge");
      }
      return els[id];
    },
  };
  globalThis.fetch = async () => new Response(
    JSON.stringify({
      recent_turns: [],
      state_snapshot: {},
      scene_entities: [{ id: "IT_X", name: "门", available: true, gate: "", reason: "" }],
      llm_records: [],
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );

  assert.equal(state.debug, false);
  const pending = toggleDebug();
  assert.equal(reloaded, false);
  assert.equal(state.debug, true);
  assert.equal(localStorage.getItem("trpg_debug"), "1");
  assert.equal(localStorage.getItem("DEBUG"), null);
  assert.equal(els["debug-panel"].classList.contains("hidden"), false);
  assert.equal(els["debug-badge"].classList.contains("hidden"), false);
  await pending;
  assert.equal(els["debug-entities-body"].innerHTML.includes("IT_X"), true);

  toggleDebug();
  assert.equal(reloaded, false);
  assert.equal(state.debug, false);
  assert.equal(localStorage.getItem("trpg_debug"), null);
  assert.equal(els["debug-panel"].classList.contains("hidden"), true);
  syncDebugUi();
  assert.equal(els["debug-panel"].classList.contains("hidden"), true);
});
