let ws = null;
let wsRetry = 0;

export function connectWS() {
  if (ws) {
    try { ws.close(); } catch (e) { /* ignore */ }
  }
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(protocol + "//" + location.host + "/api/game/progress");
  ws.onopen = function () { wsRetry = 0; };
  ws.onmessage = function (e) {
    const data = JSON.parse(e.data);
    const indicator = document.getElementById("step-indicator");
    if (!indicator) return;
    if (data.step === "heartbeat") return;
    if (data.step === "complete") {
      indicator.innerHTML = '<span class="text-aged-gold">完成</span>';
    } else {
      indicator.innerHTML =
        data.step +
        ' <span class="' +
        (data.status === "done" ? "text-coc-green" : "text-gray-500") +
        '">' +
        (data.status === "done" ? "[OK]" : "...") +
        "</span>";
    }
  };
  ws.onerror = function () {};
  ws.onclose = function () {
    ws = null;
    const screen = document.getElementById("game-screen");
    if (screen && screen.style.display !== "none") {
      wsRetry++;
      const delay = Math.min(1000 * Math.pow(2, wsRetry), 30000);
      setTimeout(connectWS, delay);
    }
  };
}
