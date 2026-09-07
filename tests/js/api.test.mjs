import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { postForm, postJSON, get } from "../../frontend/static/js/api.js";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = originalFetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("postForm sends FormData and parses JSON", async () => {
  let captured;
  globalThis.fetch = async (url, opts) => {
    captured = { url, opts };
    return jsonResponse({ brief: "ok" });
  };
  const fd = new FormData();
  fd.append("user_input", "搜索桌子");
  const data = await postForm("/api/game/turn", fd);
  assert.equal(captured.url, "/api/game/turn");
  assert.equal(captured.opts.method, "POST");
  assert.ok(captured.opts.body instanceof FormData);
  assert.equal(captured.opts.body.get("user_input"), "搜索桌子");
  const headers = captured.opts.headers || {};
  assert.equal(headers["Content-Type"] ?? headers["content-type"], undefined);
  assert.deepEqual(data, { brief: "ok" });
});

test("postForm returns {html} when content-type is not JSON", async () => {
  globalThis.fetch = async () =>
    new Response("<div>engine error</div>", {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  const data = await postForm("/api/game/turn", new FormData());
  assert.deepEqual(data, { html: "<div>engine error</div>" });
});

test("postForm throws on HTTP error and keeps body", async () => {
  globalThis.fetch = async () =>
    new Response("boom", { status: 500, headers: { "content-type": "text/plain" } });
  await assert.rejects(
    () => postForm("/api/game/turn", new FormData()),
    (err) => {
      assert.match(err.message, /500/);
      assert.equal(err.status, 500);
      assert.equal(err.body, "boom");
      return true;
    },
  );
});

test("postJSON sends JSON body", async () => {
  let captured;
  globalThis.fetch = async (url, opts) => {
    captured = { url, opts };
    return jsonResponse({ auto_win: true });
  };
  const data = await postJSON("/api/game/autowin", { enabled: true });
  assert.equal(captured.opts.headers["Content-Type"], "application/json");
  assert.equal(captured.opts.body, JSON.stringify({ enabled: true }));
  assert.deepEqual(data, { auto_win: true });
});

test("get branches on content-type", async () => {
  globalThis.fetch = async () => jsonResponse({ hp: 10 });
  assert.deepEqual(await get("/api/game/player-status?format=json"), { hp: 10 });

  globalThis.fetch = async () =>
    new Response("<p>card</p>", {
      status: 200,
      headers: { "content-type": "text/html" },
    });
  assert.deepEqual(await get("/api/game/character-card"), { html: "<p>card</p>" });
});
