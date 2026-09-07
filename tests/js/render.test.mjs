import { test } from "node:test";
import assert from "node:assert/strict";
import { renderTurnDynamic, renderSkillChips, handleTurnResponse } from "../../frontend/static/js/scene.js";
import { bumpTargetCount } from "../../frontend/static/js/combat.js";

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

test("renderTurnDynamic escapes XSS in narrative", () => {
  const html = renderTurnDynamic("[叙事] <img src=x onerror=alert(1)>");
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("&lt;img"), true);
});

test("renderTurnDynamic escapes brief and ending-like fallback text", () => {
  const html = renderTurnDynamic("[概要] a <b>b</b>");
  assert.equal(html.includes("<b>"), false);
  assert.equal(html.includes("&lt;b&gt;"), true);
});

test("renderSkillChips escapes enhancement and tooltip", () => {
  const html = renderSkillChips([
    {
      entity_id: "IT_X",
      tier: "regular",
      success: true,
      raw_roll: 20,
      target: 50,
      enhancement: { detail_override: "<script>", reason: '"onclick' },
    },
  ]);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;script&gt;"), true);
});

test("bumpTargetCount increments then resets at limit", () => {
  let counts = {};
  counts = bumpTargetCount(counts, "e1", 2);
  assert.deepEqual(counts, { e1: 1 });
  counts = bumpTargetCount(counts, "e1", 2);
  assert.deepEqual(counts, { e1: 2 });
  counts = bumpTargetCount(counts, "e1", 2);
  assert.equal(counts.e1, undefined);
});

test("handleTurnResponse slash payload does not echo brief", () => {
  const els = installDom();
  handleTurnResponse("/help", {
    brief: "",
    narrative: "/scene  /char  /flags",
    slash: { text: "/scene  /char  /flags" },
  });
  const html = els["turn-output"].innerHTML;
  assert.equal(html.includes("turn-brief"), false);
  assert.equal(html.includes("/scene"), true);
  assert.equal((html.match(/\/scene/g) || []).length, 1);
});

test("handleTurnResponse escapes slash narrative text", () => {
  const els = installDom();
  handleTurnResponse("/help", {
    brief: "",
    narrative: '<img src=x onerror=alert(1)>',
    slash: { text: '<img src=x onerror=alert(1)>' },
  });
  const html = els["turn-output"].innerHTML;
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("&lt;img"), true);
});

test("handleTurnResponse escapes leftover narrative_html", () => {
  const els = installDom();
  handleTurnResponse("/x", { narrative_html: '<img src=x onerror=alert(1)>' });
  const html = els["turn-output"].innerHTML;
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("&lt;img"), true);
});

test("handleTurnResponse renders escaped debug.evaluated into panel", () => {
  const els = installDom();
  handleTurnResponse("看", {
    narrative: "ok",
    debug: {
      evaluated: [{
        id: "<img src=x onerror=alert(1)>",
        available: false,
        gate: "requirement",
        reason: "<script>x</script>",
      }],
      matched: [],
    },
    skill_results: [{
      entity_id: "<b>IT_X</b>",
      tier: "regular",
      success: true,
      raw_roll: 20,
      target: 50,
    }],
  });
  const html = els["debug-trace-body"].innerHTML;
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
  const skills = els["debug-skills-body"].innerHTML;
  assert.equal(skills.includes("<b>IT_X</b>"), false);
  assert.equal(skills.includes("&lt;b&gt;"), true);
});

test("handleTurnResponse debug panel shows production raw_check", () => {
  const els = installDom();
  handleTurnResponse("搜索", {
    narrative: "ok",
    debug: { evaluated: [], matched: [] },
    skill_results: [{
      entity_id: "IT_SEARCH",
      entity_type: "interaction",
      tier: "regular",
      success: true,
      raw_check: "侦查检定：D100=45/50",
    }],
  });
  const skills = els["debug-skills-body"].innerHTML;
  assert.match(skills, /侦查检定：D100=45\/50/);
});
