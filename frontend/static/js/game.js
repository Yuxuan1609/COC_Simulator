import { state, loadState } from "./state.js";
import { escapeHtml } from "./util.js";
import { get } from "./api.js";
import {
  initGame,
  sendTurn,
  sendTurnAction,
  toggleSceneCard,
  toggleInlineChat,
  toggleDebug,
  toggleAutoWin,
  syncAutoWin,
  talkToNpc,
  openEnemyDetail,
  closeEnemyDetail,
} from "./scene.js";
import {
  toggleCombatPanel,
  executeCombatRound,
  selectCombatAction,
  selectCombatTarget,
} from "./combat.js";
import { toggleCharCard, updateCharHUD } from "./charcard.js";
import { connectWS } from "./ws.js";

window.initGame = initGame;
window.sendTurn = sendTurn;
window.sendTurnAction = sendTurnAction;
window.toggleSceneCard = toggleSceneCard;
window.toggleCombatPanel = toggleCombatPanel;
window.executeCombatRound = executeCombatRound;
window.toggleInlineChat = toggleInlineChat;
window.toggleDebug = toggleDebug;
window.toggleAutoWin = toggleAutoWin;
window.toggleCharCard = toggleCharCard;
window.closeEnemyDetail = closeEnemyDetail;
window.talkToNpc = talkToNpc;
window.openEnemyDetail = openEnemyDetail;
window.selectCombatAction = selectCombatAction;
window.selectCombatTarget = selectCombatTarget;

function applyDebugQuery() {
  const q = new URLSearchParams(location.search).get("debug");
  if (q === "1") localStorage.setItem("trpg_debug", "1");
  if (q === "0") localStorage.removeItem("trpg_debug");
  loadState();
}

function paintDebugUi() {
  if (!state.debug) return;
  const badge = document.getElementById("debug-badge");
  if (badge) badge.classList.remove("hidden");
  const btn = document.getElementById("btn-debug");
  if (btn) {
    btn.classList.remove("text-gray-500", "border-gray-700");
    btn.classList.add("text-yellow-400", "border-yellow-500/60", "bg-yellow-500/10");
  }
}

async function bootstrapExistingGame() {
  try {
    const st = await get("/api/game/state");
    if (!st || st.html) return;
    if (st.location && st.name) {
      updateCharHUD({
        name: st.name,
        hp: st.hp,
        hp_max: st.hp_max || st.hp,
        mp: st.mp,
        mp_max: st.mp_max,
        san: st.san,
        san_max: st.san_max || 99,
        known_spells: st.known_spells || [],
      });
      document.getElementById("game-setup").style.display = "none";
      document.getElementById("game-screen").style.display = "";
      document.getElementById("user-input").focus();
      document.getElementById("turn-output").innerHTML =
        '<div class="turn-empty text-sm text-gray-500 italic">' +
        escapeHtml(st.location) +
        " — 游戏已就绪</div>";
      connectWS();
    }
  } catch (e) { /* 未开局 */ }
}

applyDebugQuery();
document.addEventListener("DOMContentLoaded", function () {
  paintDebugUi();
  syncAutoWin();
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && e.target.id === "user-input") sendTurn();
});
bootstrapExistingGame();
