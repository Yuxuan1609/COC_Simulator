import { postJSON, get } from "./api.js";
import { state } from "./state.js";
import { escapeHtml } from "./util.js";
import { updateCharHUD } from "./charcard.js";
import { addToHistory } from "./scene.js";

function resetSelections() {
  state.combatSelections = { actionId: null, weaponId: null, targetCounts: {}, playerExtra: "" };
}

export function bumpTargetCount(counts, instanceId, multiAttack) {
  const next = { ...counts };
  const current = next[instanceId] || 0;
  const total = Object.values(next).reduce((a, b) => a + b, 0);
  if (current > 0) {
    if (total < multiAttack) next[instanceId] = current + 1;
    else next[instanceId] = 0;
  } else if (total < multiAttack) {
    next[instanceId] = 1;
  }
  if (next[instanceId] === 0) delete next[instanceId];
  return next;
}

function aliveEnemiesFrom(st) {
  const alive = [];
  (st.enemies || []).forEach(function (e) {
    if (e.hp > 0 && e.status !== "dead" && e.status !== "defeated") alive.push(e);
  });
  return alive;
}

export function enterCombatMode(combatInit) {
  state.combatSession = { combatInit: combatInit, sessionId: null, state: null, actions: [] };
  resetSelections();
  state.combatPanelCollapsed = false;

  document.getElementById("scene-panel").classList.add("hidden");
  document.getElementById("combat-panel").classList.remove("hidden");

  document.getElementById("user-input").disabled = true;
  document.getElementById("user-input").placeholder = "战斗中...";

  postJSON("/api/combat/start", { combat_init: combatInit })
    .then(function (data) {
      if (data.error) {
        alert("战斗初始化失败: " + data.error);
        exitCombatMode();
        return;
      }
      if (data.auto_win) {
        exitCombatMode();
        const outputArea = document.getElementById("turn-output");
        let winHtml =
          '<div class="turn-combat px-3 py-2 border-l-2 border-coc-green/60 bg-[#0a1a0a]/60 rounded-r">' +
          '<span class="text-sm font-bold text-coc-green">战斗 胜利（自动）</span></div>';
        if (data.combat_completed_narrative) {
          winHtml +=
            '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
            escapeHtml(data.combat_completed_narrative).replace(/\n/g, "<br>") +
            "</div>";
        }
        outputArea.insertAdjacentHTML("beforeend", winHtml);
        addToHistory("[自动胜利]", winHtml);
        get("/api/game/player-status?format=json")
          .then(updateCharHUD)
          .catch(function () {});
        get("/api/game/state").catch(function () {});
        return;
      }
      state.combatSession.sessionId = data.session_id;
      state.combatSession.state = data.state;
      state.combatSession.actions = data.actions;
      renderCombatPanel();
    })
    .catch(function (e) {
      console.error("combat start error", e);
      alert("战斗初始化失败");
      exitCombatMode();
    });
}

export function toggleCombatPanel() {
  state.combatPanelCollapsed = !state.combatPanelCollapsed;
  const inner = document.getElementById("combat-panel-inner");
  if (state.combatPanelCollapsed) inner.classList.add("hidden");
  else inner.classList.remove("hidden");
}

export function renderCombatPanel() {
  if (!state.combatSession || !state.combatSession.state) return;
  const st = state.combatSession.state;

  const pName = document.getElementById("char-name").textContent || "调查员";
  document.getElementById("combat-player-name").textContent = pName;

  const hpPct = st.player_hp_max > 0 ? (st.player_hp / st.player_hp_max * 100) : 0;
  const sanPct = st.player_san > 0 ? (st.player_san / Math.max(1, st.player_san_max || 99) * 100) : 0;
  document.getElementById("combat-hp-text").textContent = st.player_hp + "/" + st.player_hp_max;
  document.getElementById("combat-san-text").textContent = st.player_san;
  document.getElementById("combat-hp-bar").style.width = hpPct + "%";
  document.getElementById("combat-san-bar").style.width = sanPct + "%";

  const enemiesEl = document.getElementById("combat-enemies");
  let enemiesHtml = "";
  const alive = [];
  (st.enemies || []).forEach(function (e) {
    if (e.hp <= 0 || e.status === "dead" || e.status === "defeated") return;
    alive.push(e);
    const eHpPct = e.hp_max > 0 ? (e.hp / e.hp_max * 100) : 0;
    const eHpColor = eHpPct > 50 ? "bg-red-500" : eHpPct > 20 ? "bg-red-600" : "bg-red-800";
    let debugInfo = "";
    if (state.debug) {
      const bits = [];
      if (e.armor) bits.push("护甲:" + e.armor);
      if (e.san_loss) bits.push("SAN:" + e.san_loss);
      if (e.multi_attack > 1) bits.push(e.multi_attack + "次/轮");
      if (e.phases && e.phases.length) bits.push("阶段:" + e.phases.map(function (p) { return p.name; }).join("/"));
      if (bits.length) debugInfo += '<div class="text-[9px] text-gray-600 font-mono">' + escapeHtml(bits.join(" | ")) + "</div>";
      if (e.boss_mechanics) debugInfo += '<div class="text-[9px] text-red-300/70 leading-snug">' + escapeHtml(e.boss_mechanics) + "</div>";
    }
    enemiesHtml +=
      '<div class="text-xs">' +
      '<div class="flex justify-between text-gray-400"><span>' +
      escapeHtml(e.enemy_ref || "?") +
      (e.boss_mechanics ? ' <span class="text-[9px] text-red-500 border border-red-600/40 rounded px-0.5">BOSS</span>' : "") +
      "</span><span>" + e.hp + "/" + e.hp_max + "</span></div>" +
      '<div class="h-1 bg-gray-800 rounded overflow-hidden"><div class="h-full ' +
      eHpColor +
      ' rounded transition-all duration-500" style="width:' + eHpPct + '%"></div></div>' +
      debugInfo +
      "</div>";
  });
  if (!enemiesHtml) enemiesHtml = '<div class="text-xs text-gray-500">无存活敌人</div>';
  enemiesEl.innerHTML = enemiesHtml;

  const actionsEl = document.getElementById("combat-actions");
  const actionButtons = [
    { id: "attack", label: "攻击", icon: "⚔" },
    { id: "dodge", label: "回避", icon: "🛡" },
    { id: "flee", label: "逃跑", icon: "🏃" },
    { id: "conceal", label: "隐蔽", icon: "👤" },
    { id: "aim", label: "瞄准", icon: "🎯" },
    { id: "charge", label: "蓄力", icon: "⚡" },
  ];
  actionsEl.innerHTML = actionButtons.map(function (a) {
    const selected = state.combatSelections.actionId === a.id ? "border-aged-gold bg-aged-gold/20" : "border-gray-700 bg-[#1a150c]";
    return (
      '<button onclick="selectCombatAction(\'' + a.id + '\')" class="px-2 py-1.5 rounded border text-xs text-gray-300 hover:text-aged-gold hover:border-aged-gold/50 ' +
      selected +
      '">' + a.icon + " " + a.label + "</button>"
    );
  }).join("");

  const weaponSection = document.getElementById("combat-weapon-section");
  const targetSection = document.getElementById("combat-target-section");
  if (state.combatSelections.actionId === "attack") {
    weaponSection.classList.remove("hidden");
    targetSection.classList.remove("hidden");

    const weaponSelect = document.getElementById("combat-weapon-select");
    const weaponActions = (state.combatSession.actions || []).filter(function (a) {
      return a.id && a.id.startsWith("weapon:");
    });
    const baseActions = [{ id: "punch", label: "拳击" }, { id: "kick", label: "踢击" }];
    const allWeapons = baseActions.concat(weaponActions.map(function (w) { return { id: w.id, label: w.label }; }));
    weaponSelect.innerHTML = allWeapons.map(function (w) {
      return (
        '<option value="' + escapeHtml(w.id) + '"' +
        (state.combatSelections.weaponId === w.id ? " selected" : "") +
        ">" + escapeHtml(w.label) + "</option>"
      );
    }).join("");
    if (!state.combatSelections.weaponId && allWeapons.length > 0) {
      state.combatSelections.weaponId = allWeapons[0].id;
    }
    weaponSelect.onchange = function () {
      state.combatSelections.weaponId = this.value;
      renderCombatTargetButtons();
    };
    renderCombatTargetButtons(alive);
  } else {
    weaponSection.classList.add("hidden");
    targetSection.classList.add("hidden");
  }

  const executeBtn = document.getElementById("combat-execute-btn");
  if (!state.combatSelections.actionId) {
    executeBtn.disabled = true;
    executeBtn.classList.add("opacity-50");
  } else {
    executeBtn.disabled = false;
    executeBtn.classList.remove("opacity-50");
  }
}

export function renderCombatTargetButtons(alive) {
  const targetsEl = document.getElementById("combat-targets");
  const hintEl = document.getElementById("combat-target-hint");
  if (!alive) alive = aliveEnemiesFrom(state.combatSession.state);

  let multiAttack = 1;
  if (state.combatSelections.weaponId) {
    const weaponAction = (state.combatSession.actions || []).find(function (a) {
      return a.id === state.combatSelections.weaponId;
    });
    if (weaponAction) multiAttack = weaponAction.multi_attack || 1;
  }

  let totalAssigned = 0;
  targetsEl.innerHTML = alive.map(function (e) {
    const count = state.combatSelections.targetCounts[e.instance_id] || 0;
    totalAssigned += count;
    const cls = count > 0 ? "bg-aged-gold/30 border-aged-gold text-aged-gold" : "border-gray-700 text-gray-400";
    return (
      '<button onclick="selectCombatTarget(\'' + e.instance_id + "', " + multiAttack +
      ')" class="px-2 py-1 rounded border text-xs ' + cls + '">' +
      escapeHtml(e.enemy_ref || "?") + (count > 0 ? " ×" + count : "") + "</button>"
    );
  }).join("");

  const remaining = multiAttack - totalAssigned;
  if (remaining > 0) {
    hintEl.textContent = "还可分配 " + remaining + " 次攻击";
    hintEl.className = "text-[10px] text-yellow-400 mt-1";
  } else if (totalAssigned > multiAttack) {
    hintEl.textContent = "攻击次数超出，将只使用前 " + multiAttack + " 个";
    hintEl.className = "text-[10px] text-red-400 mt-1";
  } else {
    hintEl.textContent = "攻击次数已分配完毕";
    hintEl.className = "text-[10px] text-coc-green mt-1";
  }
}

export function selectCombatAction(actionId) {
  state.combatSelections.actionId = actionId;
  state.combatSelections.targetCounts = {};
  if (actionId === "attack") {
    const weaponActions = (state.combatSession.actions || []).filter(function (a) {
      return a.id && a.id.startsWith("weapon:");
    });
    state.combatSelections.weaponId = weaponActions.length > 0 ? weaponActions[0].id : "punch";
  } else {
    state.combatSelections.weaponId = null;
  }
  renderCombatPanel();
}

export function selectCombatTarget(instanceId, multiAttack) {
  state.combatSelections.targetCounts = bumpTargetCount(
    state.combatSelections.targetCounts, instanceId, multiAttack,
  );
  renderCombatPanel();
}

export async function executeCombatRound() {
  if (!state.combatSession || !state.combatSession.sessionId) return;
  if (!state.combatSelections.actionId) return;

  const btn = document.getElementById("combat-execute-btn");
  btn.disabled = true;
  btn.innerHTML = "<span>执行中...</span>";

  let actionId = state.combatSelections.actionId;
  if (actionId === "attack") actionId = state.combatSelections.weaponId || "punch";

  const st = state.combatSession.state;
  const alive = aliveEnemiesFrom(st);
  alive.sort(function (a, b) { return a.instance_id.localeCompare(b.instance_id); });
  const targetIds = [];
  alive.forEach(function (e) {
    const count = state.combatSelections.targetCounts[e.instance_id] || 0;
    for (let i = 0; i < count; i++) targetIds.push(e.instance_id);
  });
  if (actionId.startsWith("weapon:") || actionId === "punch" || actionId === "kick") {
    if (targetIds.length === 0 && alive.length > 0) targetIds.push(alive[0].instance_id);
  }

  const playerExtra = document.getElementById("combat-extra").value.trim();

  try {
    const data = await postJSON("/api/combat/round", {
      session_id: state.combatSession.sessionId,
      action_id: actionId,
      target_ids: targetIds,
      player_extra: playerExtra,
    });
    if (data.error) {
      alert("战斗回合失败: " + data.error);
      btn.disabled = false;
      btn.innerHTML = "<span>执行回合</span>";
      return;
    }
    handleCombatRoundResponse(data);
  } catch (e) {
    console.error("combat round error", e);
    if (e && e.status === 409) {
      finishCombat({ silent: true });
      return;
    }
    alert("战斗回合请求失败");
    btn.disabled = false;
    btn.innerHTML = "<span>执行回合</span>";
  }
}

export function handleCombatRoundResponse(data) {
  state.combatSession.state = data.state;

  const logEl = document.getElementById("combat-log");
  let roundHeader = '<div class="text-gray-500 font-bold mt-2">—— 第' + (data.round - 1) + "轮 ——</div>";
  let roundEntries = "";
  (data.round_log || []).forEach(function (a) {
    const actor = a.actor === "player" ? "调查员" : a.actor;
    const color = a.actor === "player" ? "text-coc-green" : "text-red-400";
    let detail = "";
    if (a.action_type === "attack") {
      detail = escapeHtml(a.weapon) + " D100=" + a.roll + " " + (a.success ? "命中" : "未命中");
      if (a.success && a.damage > 0) detail += " 造成" + a.damage + "点伤害";
    } else if (a.action_type === "flee") {
      detail = "逃跑 " + (a.success ? "成功" : "失败");
    } else {
      detail = escapeHtml(a.action_type);
    }
    roundEntries += '<div class="' + color + '">' + escapeHtml(actor) + " | " + detail + "</div>";
  });
  if (data.round_narrative) {
    roundEntries +=
      '<div class="text-gray-500 italic">' +
      escapeHtml(data.round_narrative).replace(/\n/g, "<br>") +
      "</div>";
  }
  logEl.innerHTML += roundHeader + roundEntries;

  if (data.finished) {
    finishCombat(data);
    return;
  }

  resetSelections();
  document.getElementById("combat-extra").value = "";
  renderCombatPanel();
  const btn = document.getElementById("combat-execute-btn");
  btn.disabled = false;
  btn.innerHTML = "<span>执行回合</span>";
}

export function finishCombat(data) {
  const silent = data === true || (data && data.silent === true);
  const outputArea = document.getElementById("turn-output");
  if (!silent && data) {
    const outcomeLabel =
      data.outcome === "win" ? "胜利" :
      data.outcome === "loss" ? "败北" :
      data.outcome === "flee" ? "逃跑成功" :
      data.outcome === "draw" ? "平局" : data.outcome;
    const outcomeColor =
      data.outcome === "win" ? "text-coc-green" :
      data.outcome === "loss" ? "text-coc-red" : "text-yellow-400";
    let summaryHtml =
      '<div class="px-3 py-2 border-l-2 border-yellow-600/60 bg-[#1a1400]/60 rounded-r mt-2">' +
      '<div class="flex items-center gap-2"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/></svg>' +
      '<span class="text-sm font-bold ' + outcomeColor + '">战斗 ' + escapeHtml(String(outcomeLabel || "")) + "</span></div>";
    if (data.round_narrative) {
      summaryHtml +=
        '<div class="text-gray-400 text-xs mt-1 leading-relaxed">' +
        escapeHtml(data.round_narrative).replace(/\n/g, "<br>") + "</div>";
    }
    if (data.combat_narrative) {
      summaryHtml +=
        '<div class="text-aged-gold text-xs mt-2 pt-2 border-t border-gray-700/50 leading-relaxed">' +
        escapeHtml(data.combat_narrative).replace(/\n/g, "<br>") + "</div>";
    }
    if (data.combat_completed_narrative) {
      summaryHtml +=
        '<div class="text-parchment text-sm mt-3 pt-2 border-t border-aged-gold/30 leading-relaxed narrative-flash">' +
        escapeHtml(data.combat_completed_narrative).replace(/\n/g, "<br>") + "</div>";
    }
    summaryHtml += "</div>";
    if (outputArea) {
      outputArea.innerHTML = summaryHtml;
      outputArea.scrollTop = 0;
    }
  }

  get("/api/game/player-status?format=json")
    .then(updateCharHUD)
    .catch(function () {});

  exitCombatMode();

  if (!silent && data && data.game_over && outputArea) {
    document.getElementById("user-input").disabled = true;
    setTimeout(function () {
      outputArea.insertAdjacentHTML(
        "beforeend",
        '<div class="turn-ending px-4 py-3 text-sm text-aged-gold border-l-2 border-aged-gold bg-[#1a1410]/80 mt-2">' +
        '<div class="font-bold mb-1">游戏结束</div>你在战斗中倒下...</div>',
      );
    }, 500);
  }
}

export function exitCombatMode() {
  const panel = document.getElementById("combat-panel");
  const scene = document.getElementById("scene-panel");
  if (panel) panel.classList.add("hidden");
  if (scene) scene.classList.remove("hidden");
  const input = document.getElementById("user-input");
  if (input) {
    input.disabled = false;
    input.placeholder = "输入你的行动...";
    input.focus();
  }
  const btn = document.getElementById("combat-execute-btn");
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = "<span>执行回合</span>";
  }
  state.combatSession = null;
  resetSelections();
}
