import { state, loadState, setDebug } from "./state.js";
import { escapeHtml } from "./util.js";
import { get } from "./api.js";
import { initLayout } from "./layout.js";
import {
  initGame,
  sendTurn,
  sendTurnAction,
  toggleSceneCard,
  toggleInlineChat,
  toggleAutoWin,
  syncAutoWin,
  talkToNpc,
  openEnemyDetail,
  closeEnemyDetail,
  updateSceneCard,
} from "./scene.js";
import { toggleDebug as toggleDebugPanel, syncDebugUi, refreshDebugSnapshot } from "./debug.js";
import {
  toggleCombatPanel,
  executeCombatRound,
  selectCombatAction,
  selectCombatTarget,
} from "./combat.js";
import { toggleCharCard, updateCharHUD } from "./charcard.js";
import { connectWS } from "./ws.js";

function toggleDebug() {
  const pending = toggleDebugPanel();
  if (state.lastSceneSnap) updateSceneCard(state.lastSceneSnap);
  return pending;
}

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
  if (q === "1") setDebug(true);
  if (q === "0") setDebug(false);
  loadState();
}

function paintDebugUi() {
  syncDebugUi();
  if (state.debug) refreshDebugSnapshot();
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
  initLayout();
  paintDebugUi();
  syncAutoWin();
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && e.target.id === "user-input") sendTurn();
});
bootstrapExistingGame();
