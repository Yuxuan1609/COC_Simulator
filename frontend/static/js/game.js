import { state, loadState, setDebug } from "./state.js";
import { get } from "./api.js";
import { initLayout } from "./layout.js";
import {
  initGame,
  sendTurn,
  sendTurnAction,
  toggleSceneCard,
  toggleAutoWin,
  syncAutoWin,
  talkToNpc,
  openEnemyDetail,
  closeEnemyDetail,
  updateSceneCard,
  applyBootstrapState,
} from "./scene.js";
import { toggleHistory, bindHistoryScroll } from "./history.js";
import { toggleDebug as toggleDebugPanel, syncDebugUi, refreshDebugSnapshot } from "./debug.js";
import {
  toggleCombatPanel,
  executeCombatRound,
  selectCombatAction,
  selectCombatTarget,
} from "./combat.js";
import { toggleCharCard } from "./charcard.js";
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
window.toggleHistory = toggleHistory;
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
    if (st.in_game === true) {
      applyBootstrapState(st);
      connectWS();
      if (state.debug) refreshDebugSnapshot();
    }
  } catch (e) { /* 未开局 */ }
}

applyDebugQuery();
document.addEventListener("DOMContentLoaded", function () {
  initLayout();
  paintDebugUi();
  syncAutoWin();
  bindHistoryScroll();
  bootstrapExistingGame();
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && e.target.id === "user-input") sendTurn();
});
