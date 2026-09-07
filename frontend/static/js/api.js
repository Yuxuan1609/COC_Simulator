async function parseResponse(resp, url) {
  const ct = resp.headers.get("content-type") || "";
  if (!resp.ok) {
    const body = await resp.text();
    const err = new Error(`${url} → ${resp.status}`);
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  return ct.includes("application/json") ? resp.json() : { html: await resp.text() };
}

export async function postForm(url, formData) {
  const resp = await fetch(url, { method: "POST", body: formData });
  return parseResponse(resp, url);
}

export async function postJSON(url, data) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return parseResponse(resp, url);
}

export async function get(url) {
  const resp = await fetch(url);
  return parseResponse(resp, url);
}
