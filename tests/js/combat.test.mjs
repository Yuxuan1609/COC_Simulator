import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { state } from "../../frontend/static/js/state.js";
import { executeCombatRound, finishCombat } from "../../frontend/static/js/combat.js";

const originalFetch = globalThis.fetch;

function installDom() {
  const store = {};
  function el() {
    const classes = new Set();
    return {
      classList: {
        contains(c) { return classes.has(c); },
        add(c) { classes.add(c); },
        remove(c) { classes.delete(c); },
      },
      innerHTML: "",
      textContent: "",
      style: {},
      disabled: false,
      scrollTop: 0,
      value: "",
      placeholder: "",
      focus() {},
      insertAdjacentHTML() {},
    };
  }
  globalThis.document = {
    getElementById(id) {
      if (!store[id]) store[id] = el();
      return store[id];
    },
  };
  return store;
}

beforeEach(() => {
  installDom();
  state.combatSession = null;
  state.combatSelections = { actionId: null, weaponId: null, targetCounts: {}, playerExtra: "" };
  globalThis.fetch = async () => new Response("{}", {
    status: 200,
    headers: { "content-type": "application/json" },
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  state.combatSession = null;
});

test("finishCombat silent skips outcome html and exits combat", () => {
  const panel = document.getElementById("combat-panel");
  const scene = document.getElementById("scene-panel");
  const out = document.getElementById("turn-output");
  panel.classList.remove("hidden");
  scene.classList.add("hidden");
  state.combatSession = { sessionId: "abc", state: {}, actions: [] };
  out.innerHTML = "";
  finishCombat({ silent: true });
  assert.equal(state.combatSession, null);
  assert.equal(out.innerHTML, "");
  assert.equal(panel.classList.contains("hidden"), true);
  assert.equal(scene.classList.contains("hidden"), false);
});

test("executeCombatRound 409 silently returns to exploration", async () => {
  const panel = document.getElementById("combat-panel");
  const out = document.getElementById("turn-output");
  panel.classList.remove("hidden");
  state.combatSession = {
    sessionId: "dead",
    state: { enemies: [] },
    actions: [],
  };
  state.combatSelections.actionId = "dodge";
  globalThis.fetch = async (url) => {
    if (String(url).includes("/api/combat/round")) {
      return new Response(JSON.stringify({ error: "combat_session_lost" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ hp: 10, hp_max: 12, san: 55 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  await executeCombatRound();
  assert.equal(state.combatSession, null);
  assert.equal(panel.classList.contains("hidden"), true);
  assert.equal(out.innerHTML.includes("战斗"), false);
});
