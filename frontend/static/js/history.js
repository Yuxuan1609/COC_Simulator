import { get } from "./api.js";
import { escapeHtml } from "./util.js";

let nextBefore = null;
let loading = false;
let exhausted = false;

function renderOne(item) {
  const turn = item && item.turn != null ? item.turn : "?";
  let body = "";
  if (item && item.brief) {
    body += '<div class="history-brief">' + escapeHtml(item.brief) + "</div>";
  }
  if (item && item.narrative) {
    body +=
      '<div class="history-narrative">' +
      escapeHtml(item.narrative).replace(/\n/g, "<br>") +
      "</div>";
  }
  return (
    '<div class="history-item">' +
    '<div class="history-turn">第' + escapeHtml(turn) + "回合</div>" +
    body +
    "</div>"
  );
}

export function renderHistoryItems(items) {
  if (!items || !items.length) {
    return '<div class="history-empty">暂无历史</div>';
  }
  return items.map(renderOne).join("");
}

function historyUrl(beforeTurn, limit) {
  const n = limit == null ? 20 : limit;
  let url = "/api/game/history?limit=" + encodeURIComponent(n);
  if (beforeTurn != null && beforeTurn !== "") {
    url += "&before_turn=" + encodeURIComponent(beforeTurn);
  }
  return url;
}

export async function loadHistory(reset) {
  if (loading) return;
  if (!reset && (exhausted || nextBefore == null)) return;
  loading = true;
  try {
    const url = reset ? historyUrl(null, 20) : historyUrl(nextBefore, 20);
    const data = await get(url);
    if (!data || data.html || data.error) return;
    const list = document.getElementById("history-list");
    if (!list) return;
    const items = data.items || [];
    if (reset) {
      list.innerHTML = renderHistoryItems(items);
      list.scrollTop = 0;
    } else if (items.length) {
      list.insertAdjacentHTML("beforeend", items.map(renderOne).join(""));
    }
    nextBefore = data.next_before == null ? null : data.next_before;
    exhausted = nextBefore == null || !items.length;
  } catch {
    /* 历史拉取失败不挡主流程 */
  } finally {
    loading = false;
  }
}

export function bindHistoryScroll() {
  const list = document.getElementById("history-list");
  if (!list || list.dataset.historyBound === "1") return;
  list.dataset.historyBound = "1";
  list.addEventListener("scroll", function () {
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 24) {
      loadHistory(false);
    }
  });
}

export function toggleHistory() {
  const panel = document.getElementById("history-panel");
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !opening);
  panel.setAttribute("aria-hidden", opening ? "false" : "true");
  if (opening) {
    nextBefore = null;
    exhausted = false;
    bindHistoryScroll();
    return loadHistory(true);
  }
}
