import { test } from "node:test";
import assert from "node:assert/strict";
import { escapeHtml } from "../../frontend/static/js/util.js";

test("escapeHtml encodes HTML metacharacters", () => {
  assert.equal(
    escapeHtml(`<img src=x onerror="alert(1)">&'"/`),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;&quot;/",
  );
});

test("escapeHtml treats nullish as empty string", () => {
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
  assert.equal(escapeHtml(""), "");
});

test("escapeHtml stringifies numbers", () => {
  assert.equal(escapeHtml(12), "12");
});
