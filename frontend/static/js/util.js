/** HTML escape for any player/LLM text that goes into innerHTML. */
export function escapeHtml(text) {
  if (text === null || text === undefined) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function isHtmlFallback(data) {
  return !!(
    data &&
    typeof data === "object" &&
    typeof data.html === "string" &&
    !("status" in data) &&
    !("narrative" in data) &&
    !("brief" in data)
  );
}

export function jsStringLiteral(value) {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}
