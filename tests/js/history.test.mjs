import { test } from "node:test";
import assert from "node:assert/strict";
import { renderHistoryItems } from "../../frontend/static/js/history.js";

test("renderHistoryItems escapes turn/brief/narrative XSS", () => {
  const html = renderHistoryItems([{
    turn: '<img src=x onerror=alert(1)>',
    brief: "<b>brief</b>",
    narrative: '<script>alert(1)</script>\nnext',
  }]);
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("<b>brief</b>"), false);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;img"), true);
  assert.equal(html.includes("&lt;b&gt;brief&lt;/b&gt;"), true);
  assert.equal(html.includes("&lt;script&gt;"), true);
  assert.equal(html.includes("<br>"), true);
});

test("renderHistoryItems empty state", () => {
  assert.match(renderHistoryItems([]), /暂无历史/);
  assert.match(renderHistoryItems(null), /暂无历史/);
});
