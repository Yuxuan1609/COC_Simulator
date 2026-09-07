import { test } from "node:test";
import assert from "node:assert/strict";
import { applyBootstrapState } from "../../frontend/static/js/scene.js";

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
      style: { display: "" },
      disabled: false,
      scrollTop: 0,
      value: "",
      placeholder: "",
      title: "",
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

test("applyBootstrapState leaves setup visible when in_game is false", () => {
  const els = installDom();
  const setup = document.getElementById("game-setup");
  const screen = document.getElementById("game-screen");
  setup.style.display = "";
  screen.style.display = "none";
  const ok = applyBootstrapState({
    in_game: false, location: "书房", name: "张三", hp: 10, hp_max: 12,
  });
  assert.equal(ok, false);
  assert.notEqual(els["game-setup"].style.display, "none");
  assert.equal(els["game-screen"].style.display, "none");
});

test("applyBootstrapState shows game screen when in_game is true", () => {
  const els = installDom();
  document.getElementById("game-setup").style.display = "";
  document.getElementById("game-screen").style.display = "none";
  const ok = applyBootstrapState({
    in_game: true,
    location: "书房",
    name: "张三",
    hp: 10,
    hp_max: 12,
    mp: 8,
    mp_max: 11,
    san: 55,
    san_max: 88,
    known_spells: [],
  });
  assert.equal(ok, true);
  assert.equal(els["game-setup"].style.display, "none");
  assert.equal(els["game-screen"].style.display, "");
  assert.match(els["turn-output"].innerHTML, /书房/);
});
