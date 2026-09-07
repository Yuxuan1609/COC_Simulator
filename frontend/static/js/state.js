function lsGet(key) {
  try {
    if (typeof localStorage === "undefined") return null;
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function lsSet(key, val) {
  try {
    if (typeof localStorage === "undefined") return;
    if (val === null) localStorage.removeItem(key);
    else localStorage.setItem(key, val);
  } catch {
    /* ignore quota / private mode */
  }
}

export const state = {
  combatSession: null,
  combatSelections: { actionId: null, weaponId: null, targetCounts: {}, playerExtra: "" },
  combatPanelCollapsed: false,
  debug: false,
  autoWin: false,
  chatMessages: [],
  sceneCardExpanded: false,
  inlineChatVisible: false,
  lastSceneEnemies: [],
  switches: {},
};

export function loadState() {
  state.debug = lsGet("trpg_debug") === "1";
  state.autoWin = lsGet("trpg_autowin") === "1";
  try {
    state.switches = JSON.parse(lsGet("switches") || "{}") || {};
  } catch {
    state.switches = {};
  }
  return state;
}

export function setSwitch(k, v) {
  if (k === "debug") return setDebug(v);
  if (k === "autoWin") return setAutoWin(v);
  state.switches[k] = v;
  lsSet("switches", JSON.stringify(state.switches));
}

export function setDebug(on) {
  state.debug = !!on;
  lsSet("trpg_debug", on ? "1" : null);
}

export function setAutoWin(on) {
  state.autoWin = !!on;
  lsSet("trpg_autowin", on ? "1" : null);
}

loadState();
