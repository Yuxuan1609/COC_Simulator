import { test } from "node:test";
import assert from "node:assert/strict";
import { renderCharacterCard } from "../../frontend/static/js/charcard.js";

const BASE = {
  name: "张三",
  age: 30,
  gender: "男",
  occupation: "记者",
  avatar_url: "",
  appearance: "",
  personal_description: "",
  stats: { STR: 60, CON: 65, SIZ: 55, DEX: 70, APP: 50, INT: 75, POW: 70, EDU: 80, LUCK: 50 },
  hp: 10,
  hp_max: 12,
  san: 55,
  san_max: 88,
  mp: 8,
  mp_max: 11,
  mov: 8,
  db: "1D4",
  build: 1,
  dodge: 50,
  skills: [{ name: "侦查", value: 60, category: "感知" }],
  weapons: [{ name: "小刀", damage: "1D4" }],
  spells: [
    { id: "HEART_ARREST", name: "心脏骤停", category: "战斗" },
    { id: "GHOST", name: "GHOST", category: null },
  ],
  items: "无",
};

test("renderCharacterCard shows 无调查员 when name is null", () => {
  const html = renderCharacterCard({ name: null });
  assert.match(html, /无调查员/);
});

test("renderCharacterCard SAN bar uses san_max (F2: 55/88 → 62.5%)", () => {
  const html = renderCharacterCard(BASE);
  assert.match(html, /62\.5%/);
  assert.match(html, /8\/11/);
  assert.match(html, /心脏骤停/);
  assert.match(html, /GHOST/);
});

test("renderCharacterCard escapes player-derived strings", () => {
  const html = renderCharacterCard({
    ...BASE,
    name: "<img src=x onerror=alert(1)>",
    appearance: "<script>x</script>",
    personal_description: "<b>hi</b>",
    occupation: "<svg onload=alert(1)>",
    items: "<img src=y>",
    spells: [{ id: "X", name: "<script>s</script>", category: "战斗" }],
    skills: [{ name: "<img>", value: 50, category: "感知" }],
    weapons: [{ name: "<b>刀</b>", damage: "1d4" }],
  });
  assert.equal(html.includes("<script"), false);
  assert.equal(html.includes("<b>hi</b>"), false);
  assert.equal(html.includes("<b>刀</b>"), false);
  assert.equal(html.includes("<img src=x"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
});
