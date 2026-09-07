import { test } from "node:test";
import assert from "node:assert/strict";
import { renderTurnDynamic, renderSkillChips } from "../../frontend/static/js/scene.js";
import { bumpTargetCount } from "../../frontend/static/js/combat.js";

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
