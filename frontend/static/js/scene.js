import { postForm, postJSON, get } from "./api.js";
import { state, setSwitch } from "./state.js";
import { escapeHtml, isHtmlFallback, jsStringLiteral } from "./util.js";
import { updateCharHUD } from "./charcard.js";
import { connectWS } from "./ws.js";
import { enterCombatMode } from "./combat.js";
import { paintSwitch } from "./layout.js";

export function toggleSceneCard() {
  state.sceneCardExpanded = !state.sceneCardExpanded;
  const expanded = document.getElementById("scene-panel-expanded");
  const collapsed = document.getElementById("scene-panel-collapsed");
  if (state.sceneCardExpanded) {
    expanded.classList.remove("hidden");
    collapsed.classList.add("hidden");
  } else {
    expanded.classList.add("hidden");
    collapsed.classList.remove("hidden");
  }
}

export function updateSceneCard(snap) {
  if (!snap) return;
  let timeStr = "";
  if (snap.time && snap.time.game_time !== undefined) {
    const gt = snap.time.game_time;
    const day = Math.floor(gt / 1440);
    const hour = Math.floor((gt % 1440) / 60);
    const min = gt % 60;
    if (day) timeStr += "第" + day + "天 ";
    timeStr += (hour < 10 ? "0" : "") + hour + ":" + (min < 10 ? "0" : "") + min;
  }

  document.getElementById("scene-panel-name").textContent = snap.scene_name || "--";
  document.getElementById("scene-panel-time").textContent = timeStr || "--:--";
  document.getElementById("scene-card-name-expanded").textContent = snap.scene_name || "--";
  document.getElementById("scene-card-desc").textContent = snap.scene_description || "（无场景描述）";
  document.getElementById("scene-card-time-full").textContent = timeStr || "--";

  const exitsWrap = document.getElementById("scene-card-exits-wrap");
  const exitsEl = document.getElementById("scene-card-exits");
  const exits = snap.exits || [];
  if (exits.length > 0) {
    exitsWrap.classList.remove("hidden");
    exitsEl.innerHTML = exits.map(function (e) {
      const t = jsStringLiteral(e.target || "");
      return (
        '<button onclick="sendTurnAction(\'move\', \'' + t + '\')" ' +
        'class="text-[10px] px-1.5 py-0.5 bg-gray-800 hover:bg-aged-brown rounded text-gray-400 hover:text-parchment border border-gray-700 hover:border-aged-gold/50 transition-colors cursor-pointer">' +
        escapeHtml(e.target || "?") +
        '<span class="text-gray-600 ml-0.5">· ' + escapeHtml(e.method || "?") + "</span></button>"
      );
    }).join("");
  } else {
    exitsWrap.classList.add("hidden");
  }

  const qaExits = document.getElementById("qa-exits");
  if (qaExits && exits.length > 0) {
    qaExits.innerHTML = exits.map(function (e) {
      const t = jsStringLiteral(e.target || "");
      return (
        '<button onclick="sendTurnAction(\'move\', \'' + t + '\')" ' +
        'class="px-2 py-0.5 text-[10px] bg-gray-800 hover:bg-aged-brown text-gray-400 hover:text-parchment rounded border border-gray-700 hover:border-aged-gold/50 transition-colors cursor-pointer">' +
        "→ " + escapeHtml(e.target || "?") + "</button>"
      );
    }).join("");
  }

  const npcsWrap = document.getElementById("scene-card-npcs-wrap");
  const npcsEl = document.getElementById("scene-card-npcs");
  const npcs = snap.npcs || [];
  if (npcs.length > 0) {
    const attCls = {
      hostile: "text-red-400 border-red-600/40",
      wary: "text-yellow-400 border-yellow-600/40",
      friendly: "text-green-400 border-green-600/40",
      neutral: "text-gray-400 border-gray-600/40",
    };
    const attLabel = { hostile: "敌对", wary: "戒备", friendly: "友善", neutral: "中立" };
    npcsWrap.classList.remove("hidden");
    npcsEl.innerHTML = npcs.map(function (n) {
      const att = n.attitude || "";
      const badge = att
        ? '<span class="inline-block px-1 rounded border text-[9px] ml-1 ' +
          (attCls[att] || attCls.neutral) +
          '">' +
          escapeHtml(attLabel[att] || att) +
          "</span>"
        : "";
      const following = n.following
        ? '<span class="inline-block px-1 rounded border border-coc-green/40 text-coc-green text-[9px] ml-1">跟随中</span>'
        : "";
      const talkBtn =
        '<button onclick="talkToNpc(\'' +
        jsStringLiteral(n.name || "") +
        '\')" class="ml-1 px-1.5 py-0 text-[9px] bg-gray-800 hover:bg-aged-brown text-gray-400 hover:text-parchment rounded border border-gray-700 hover:border-aged-gold/50 transition-colors cursor-pointer">交谈</button>';
      return (
        '<div class="text-[10px] text-gray-400">' +
        '<span class="text-aged-gold font-bold">' +
        escapeHtml(n.name || "?") +
        "</span>" +
        badge +
        following +
        talkBtn +
        (n.demeanor ? ' <span class="text-gray-500">(' + escapeHtml(n.demeanor) + ")</span>" : "") +
        (n.brief ? '<div class="text-gray-500 mt-0.5 leading-relaxed">' + escapeHtml(n.brief) + "</div>" : "") +
        "</div>"
      );
    }).join("");
  } else {
    npcsWrap.classList.add("hidden");
  }

  const enemiesWrap = document.getElementById("scene-card-enemies-wrap");
  const enemiesEl = document.getElementById("scene-card-enemies");
  const enemies = snap.enemies || [];
  state.lastSceneEnemies = enemies;
  if (enemies.length > 0) {
    enemiesWrap.classList.remove("hidden");
    enemiesEl.innerHTML = enemies.map(function (e, idx) {
      const qty = (e.quantity || 1) > 1 ? " ×" + e.quantity : "";
      const clickable = state.debug ? " cursor-pointer hover:bg-gray-800/60 rounded px-0.5 -mx-0.5" : "";
      const onclick = state.debug ? ' onclick="openEnemyDetail(' + idx + ')"' : "";
      const bossTag = e.boss_mechanics
        ? ' <span class="text-[9px] text-red-500 border border-red-600/40 rounded px-1">BOSS</span>'
        : "";
      return (
        '<div class="text-[10px] text-gray-400' + clickable + '"' + onclick + ">" +
        '<span class="text-red-400 font-bold">' +
        escapeHtml(e.enemy_ref || "?") + qty +
        "</span>" +
        bossTag +
        (e.status ? ' <span class="text-gray-500">[' + escapeHtml(e.status) + "]</span>" : "") +
        (state.debug && e.hp !== undefined ? ' <span class="text-gray-600">HP ' + e.hp + "</span>" : "") +
        "</div>"
      );
    }).join("");
  } else {
    enemiesWrap.classList.add("hidden");
  }

  const threatsWrap = document.getElementById("scene-card-threats-wrap");
  const threatsEl = document.getElementById("scene-card-threats");
  const threats = snap.potential_threats || [];
  if (state.debug && threats.length > 0) {
    threatsWrap.classList.remove("hidden");
    threatsEl.innerHTML = threats.map(function (t) {
      const icon = t.kind === "boss" ? "👑" : "👁";
      const cls = t.kind === "boss" ? "text-red-400" : "text-yellow-400";
      return (
        '<div class="text-[10px] ' + cls + '">' + icon + " " + escapeHtml(t.ref || "?") +
        (t.note ? ' <span class="text-gray-600">' + escapeHtml(t.note) + "</span>" : "") +
        "</div>"
      );
    }).join("");
  } else {
    threatsWrap.classList.add("hidden");
  }
}

export function talkToNpc(name) {
  const input = document.getElementById("user-input");
  if (!input || input.disabled) return;
  input.value = "与" + name + "交谈";
  sendTurn();
}

export function openEnemyDetail(idx) {
  const e = state.lastSceneEnemies[idx];
  if (!e) return;
  const d = e.detail || {};
  document.getElementById("enemy-detail-title").textContent =
    (e.enemy_ref || "?") + ((e.quantity || 1) > 1 ? " ×" + e.quantity : "");
  const rows = [];
  function row(k, v) {
    if (v) {
      rows.push(
        '<div><span class="text-gray-500">' + escapeHtml(k) +
        '：</span><span class="text-gray-300">' + escapeHtml(v) + "</span></div>",
      );
    }
  }
  row("状态", e.status);
  row("HP", e.hp);
  row("标记", (e.flags || []).join(", "));
  row("类型", d.type);
  row("护甲", d.armor);
  row("SAN 损失", d.san_loss);
  row("多重攻击", d.multi_attack > 1 ? d.multi_attack + " 次/轮" : "");
  if (d.attacks && d.attacks.length) {
    rows.push(
      '<div class="text-gray-500 mt-1">攻击：</div>' +
      d.attacks.map(function (a) {
        const dmg = a.damage || {};
        const dmgStr = dmg.dice_n
          ? dmg.dice_n + "D" + dmg.dice_d + (dmg.bonus ? "+" + dmg.bonus : "") + (dmg.use_db ? "+DB" : "")
          : "特殊";
        return (
          '<div class="pl-3 text-gray-300">· ' +
          escapeHtml(a.name) +
          "（" + escapeHtml(dmgStr) +
          (a.skill_value ? "，" + escapeHtml(a.skill_name) + " " + a.skill_value + "%" : "") +
          "）</div>"
        );
      }).join(""),
    );
  }
  if (d.special_abilities && d.special_abilities.length) {
    rows.push(
      '<div class="text-gray-500 mt-1">特殊能力：</div>' +
      d.special_abilities.map(function (s) {
        return (
          '<div class="pl-3"><span class="text-gray-300">' +
          escapeHtml(s.name) +
          '</span> <span class="text-gray-500">' +
          escapeHtml(s.desc) +
          "</span></div>"
        );
      }).join(""),
    );
  }
  if (d.phases && d.phases.length) {
    rows.push(
      '<div class="text-gray-500 mt-1">阶段：</div>' +
      d.phases.map(function (p) {
        return (
          '<div class="pl-3"><span class="text-yellow-400">' +
          escapeHtml(p.name || "?") +
          '</span> <span class="text-gray-500">[' +
          escapeHtml(p.trigger || "") +
          ']</span><div class="text-gray-500 pl-2">' +
          escapeHtml(p.description || "") +
          "</div></div>"
        );
      }).join(""),
    );
  }
  if (e.boss_mechanics) {
    rows.push(
      '<div class="text-gray-500 mt-1">Boss 机制：</div><div class="pl-3 text-red-300/80">' +
      escapeHtml(e.boss_mechanics) +
      "</div>",
    );
  }
  row("描述", d.description);
  document.getElementById("enemy-detail-body").innerHTML =
    rows.join("") || '<div class="text-gray-600">无详细数据</div>';
  document.getElementById("enemy-detail-modal").classList.remove("hidden");
}

export function closeEnemyDetail() {
  document.getElementById("enemy-detail-modal").classList.add("hidden");
}

export async function initGame(e) {
  console.log("[initGame] begin");
  e.preventDefault();
  const form = document.getElementById("init-form");
  const fd = new FormData(form);
  fd.append("weapon_path", "");
  fd.append("enemy_path", "");
  fd.append("boss_path", "");
  const errEl = document.getElementById("init-error");
  errEl.textContent = "";
  for (const id of ["l2-path", "l1-path", "l3-path"]) {
    if (!document.getElementById(id).value.trim()) {
      errEl.textContent = "请填写所有模组文件路径";
      console.log("[initGame] validation failed: empty", id);
      return;
    }
  }
  try {
    console.log("[initGame] sending POST /api/game/init");
    const data = await postForm("/api/game/init", fd);
    if (isHtmlFallback(data)) {
      errEl.textContent = "初始化失败: " + data.html;
      return;
    }
    console.log("[initGame] init success, location:", data.location);
    if (data.warning) {
      const toast = document.getElementById("game-toast");
      if (toast) {
        toast.textContent = data.warning;
        toast.classList.remove("hidden");
        setTimeout(function () { toast.classList.add("hidden"); }, 3000);
      }
    }
    updateCharHUD({
      name: data.name,
      hp: data.hp,
      hp_max: data.hp_max || data.hp,
      mp: data.mp,
      mp_max: data.mp_max,
      san: data.san,
      san_max: data.san_max || 99,
      known_spells: data.known_spells || [],
      avatar_url: "",
      occupation: "",
    });
    document.getElementById("game-setup").style.display = "none";
    document.getElementById("game-screen").style.display = "";
    document.getElementById("user-input").focus();
    let turnHtml = "";
    if (data.initial_brief) {
      turnHtml +=
        '<div class="turn-brief px-3 py-2 text-xs text-gray-500 border-l-2 border-gray-700 bg-[#0f0f0f]/50 rounded-r">' +
        escapeHtml(data.initial_brief) +
        "</div>";
    }
    if (data.initial_narrative) {
      turnHtml +=
        '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
        escapeHtml(data.initial_narrative).replace(/\n/g, "<br>") +
        "</div>";
    }
    document.getElementById("turn-output").innerHTML =
      turnHtml || '<div class="turn-empty text-sm text-gray-500 italic">游戏已就绪</div>';
    if (data.player_snapshot) updateSceneCard(data.player_snapshot);
    connectWS();
    console.log("[initGame] game screen shown");
  } catch (err) {
    console.error("[initGame] error:", err);
    if (err.status) errEl.textContent = "初始化失败: " + (err.body || err.message);
    else errEl.textContent = "网络错误: " + err.message;
  }
}

export function toggleInlineChat() {
  state.inlineChatVisible = !state.inlineChatVisible;
  const panel = document.getElementById("chat-history-inline");
  const label = document.getElementById("inline-chat-label");
  if (state.inlineChatVisible) {
    panel.classList.remove("hidden");
    label.textContent = "隐藏记录";
    refreshInlineChat();
  } else {
    panel.classList.add("hidden");
    label.textContent = "对话记录";
  }
}

export function refreshInlineChat() {
  const panel = document.getElementById("chat-history-inline");
  if (!panel || panel.classList.contains("hidden")) return;
  panel.innerHTML =
    state.chatMessages.slice(-20).join("") ||
    '<div class="text-xs text-gray-600 italic">暂无记录</div>';
  panel.scrollTop = panel.scrollHeight;
}

export function addToHistory(userMsg, responseHtml) {
  if (userMsg) {
    state.chatMessages.push(
      '<div class="history-user px-3 py-1 text-xs text-gray-600 border-l-2 border-gray-700 mb-1">&gt; ' +
      escapeHtml(userMsg) +
      "</div>",
    );
  }
  if (responseHtml) state.chatMessages.push(responseHtml);
  if (state.chatMessages.length > 200) state.chatMessages = state.chatMessages.slice(-200);
  refreshInlineChat();
}

export function renderTurnDynamic(text) {
  if (!text) return "";
  const blocks = text.split("\n\n");
  const html = [];
  blocks.forEach(function (block) {
    block = block.trim();
    if (!block) return;
    if (block.startsWith("[时间]")) {
      const content = block.replace("[时间]", "").trim();
      html.push('<div class="turn-time text-[10px] text-gray-500 font-mono px-3 py-1">' + escapeHtml(content) + "</div>");
    } else if (block.startsWith("[战斗]")) {
      const lines = block.split("\n");
      const title = lines[0].replace("[战斗]", "").trim();
      const narrative = lines.slice(1).join("\n").trim();
      const outcomeColor = title === "胜利" ? "text-coc-green" : title === "败北" ? "text-coc-red" : "text-yellow-400";
      html.push(
        '<div class="turn-combat px-3 py-2 border-l-2 border-yellow-600/60 bg-[#1a1400]/60 rounded-r">' +
        '<div class="flex items-center gap-2"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/></svg>' +
        '<span class="text-sm font-bold ' + outcomeColor + '">战斗 ' + escapeHtml(title) + "</span></div>" +
        (narrative ? '<div class="text-gray-400 text-xs mt-1 leading-relaxed">' + escapeHtml(narrative) + "</div>" : "") +
        "</div>",
      );
    } else if (block.startsWith("[技能检定]")) {
      const lines = block.split("\n").slice(1);
      const skillsHtml = lines.map(function (line) {
        line = line.trim();
        if (!line) return "";
        const m = line.match(/^\[(OK|FAIL)\]\s+(\S+)\s+\[(\S+)\]\s+(.*)$/);
        if (!m) return '<div class="text-xs text-gray-400">' + escapeHtml(line) + "</div>";
        const status = m[1];
        const eid = m[2];
        const tier = m[3];
        const rest = m[4];
        const diceMatch = rest.match(/D100=(\d+)\/(\d+)/);
        const diceInfo = diceMatch ? "D100=" + diceMatch[1] + "/" + diceMatch[2] : "";
        const enhText = rest.replace(diceInfo, "").trim();
        const tierColorCls = tier === "extreme" ? "text-yellow-300" : tier === "hard" ? "text-coc-green" : tier === "regular" ? "text-gray-300" : "text-red-400";
        return (
          '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border ' +
          (status === "OK" ? "border-coc-green/40 bg-coc-green/10 text-coc-green" : "border-coc-red/40 bg-coc-red/10 text-coc-red") +
          '">' +
          '<span class="font-bold">' + status + "</span>" +
          '<span class="text-gray-400">' + escapeHtml(eid) + "</span>" +
          '<span class="' + tierColorCls + '">[' + escapeHtml(tier) + "]</span>" +
          (diceInfo ? '<span class="text-gray-500">' + diceInfo + "</span>" : "") +
          (enhText ? '<span class="text-yellow-400">' + escapeHtml(enhText) + "</span>" : "") +
          "</span>"
        );
      }).filter(Boolean).join("");
      html.push('<div class="turn-skills flex flex-wrap gap-1.5 px-1">' + skillsHtml + "</div>");
    } else if (block.startsWith("[概要]")) {
      const content = block.replace("[概要]", "").trim();
      html.push(
        '<div class="turn-brief px-3 py-2 text-xs text-gray-500 border-l-2 border-gray-700 bg-[#0f0f0f]/50 rounded-r">' +
        escapeHtml(content) +
        "</div>",
      );
    } else if (block.startsWith("[叙事]")) {
      const content = block.replace("[叙事]", "").trim();
      html.push(
        '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
        escapeHtml(content).replace(/\n/g, "<br>") +
        "</div>",
      );
    } else {
      html.push('<div class="text-xs text-gray-400 px-3 py-1">' + escapeHtml(block) + "</div>");
    }
  });
  return html.join("");
}

export function renderSkillChips(checks) {
  return checks.map(function (sc) {
    const eid = sc.entity_id || "?";
    const tier = sc.tier || "regular";
    const success = sc.success !== false;
    const enh = sc.enhancement;
    let tierHtml = '<span class="' + tierColor(tier) + '">[' + escapeHtml(tier) + "]</span>";
    if (enh && enh.original_tier && enh.original_tier !== tier) {
      tierHtml =
        '<span class="text-gray-500">[' + escapeHtml(enh.original_tier) + ']</span><span class="text-yellow-400">→</span>' +
        tierHtml;
    }
    const diceInfo = sc.raw_roll ? ("D100=" + sc.raw_roll + "/" + sc.target) : "";
    let critCls = "";
    let critTag = "";
    if (sc.raw_roll && sc.raw_roll <= 5) {
      critCls = " ring-1 ring-yellow-300";
      critTag = '<span class="text-yellow-300 font-bold">大成功</span>';
    } else if (sc.raw_roll && sc.raw_roll >= 96) {
      critCls = " ring-1 ring-red-500";
      critTag = '<span class="text-red-400 font-bold">大失败</span>';
    }
    let enhText = "";
    let tooltip = "";
    if (enh) {
      enhText = enh.detail_override ? " " + enh.detail_override : "";
      tooltip = enh.reason || enh.detail_override || "";
    }
    return (
      "<span" + (tooltip ? ' title="' + escapeHtml(tooltip) + '"' : "") +
      ' class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border ' +
      (success ? "border-coc-green/40 bg-coc-green/10 text-coc-green" : "border-coc-red/40 bg-coc-red/10 text-coc-red") +
      critCls + '">' +
      '<span class="font-bold">' + (success ? "OK" : "FAIL") + "</span>" +
      '<span class="text-gray-400">' + escapeHtml(eid) + "</span>" +
      tierHtml +
      (diceInfo ? '<span class="text-gray-500">' + diceInfo + "</span>" : "") +
      critTag +
      (enhText ? '<span class="text-yellow-400">' + escapeHtml(enhText) + "</span>" : "") +
      "</span>"
    );
  }).join("");
}

export function tierColor(tier) {
  return tier === "extreme" ? "text-yellow-300" : tier === "hard" ? "text-coc-green" : tier === "regular" ? "text-gray-300" : "text-red-400";
}

export function handleTurnResponse(userText, data) {
  if (data.game_frozen) {
    const overlay = document.getElementById("freeze-overlay");
    const msg = document.getElementById("freeze-message");
    if (overlay && msg) {
      msg.textContent = data.frozen_message || "系统异常，游戏已暂停。";
      overlay.classList.remove("hidden");
    }
    const input = document.getElementById("user-input");
    if (input) input.disabled = true;
    const sendBtn = document.getElementById("send-btn");
    if (sendBtn) sendBtn.disabled = true;
    document.getElementById("step-indicator").innerHTML = "";
    return;
  }

  const snap = data.player_snapshot;
  if (snap) updateSceneCard(snap);

  if (data.combat_init && !data.combat) {
    enterCombatMode(data.combat_init);
    if (data.narrative) {
      const outputArea = document.getElementById("turn-output");
      outputArea.innerHTML =
        '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
        escapeHtml(data.narrative).replace(/\n/g, "<br>") +
        "</div>";
    }
    addToHistory(userText, data.narrative || "");
    return;
  }

  const turnParts = [];
  if (data.slash && data.slash.text) {
    turnParts.push(
      '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
      escapeHtml(data.slash.text).replace(/\n/g, "<br>") +
      "</div>",
    );
  } else if (data.turn_dynamic_text) {
    let dynText = data.turn_dynamic_text;
    const structuredChecks = (snap && snap.skill_checks) || [];
    if (structuredChecks.length > 0) {
      dynText = dynText.split("\n\n").filter(function (b) {
        return !b.trim().startsWith("[技能检定]");
      }).join("\n\n");
    }
    const dynamicHtml = renderTurnDynamic(dynText);
    if (dynamicHtml) turnParts.push(dynamicHtml);
    if (structuredChecks.length > 0) {
      turnParts.push('<div class="turn-skills flex flex-wrap gap-1.5 px-1">' + renderSkillChips(structuredChecks) + "</div>");
    }
  } else {
    const combatData = (snap && snap.combat) || data.combat;
    if (combatData) {
      const outcomeLabel = combatData.outcome === "win" ? "胜利" : combatData.outcome === "loss" ? "败北" : combatData.outcome;
      const outcomeColor = combatData.outcome === "win" ? "text-coc-green" : combatData.outcome === "loss" ? "text-coc-red" : "text-yellow-400";
      turnParts.push(
        '<div class="turn-combat px-3 py-2 border-l-2 border-yellow-600/60 bg-[#1a1400]/60 rounded-r">' +
        '<div class="flex items-center gap-2"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/></svg>' +
        '<span class="text-sm font-bold ' + outcomeColor + '">战斗 ' + escapeHtml(outcomeLabel) + "</span></div>" +
        (combatData.narrative
          ? '<div class="text-gray-400 text-xs mt-1 leading-relaxed">' + escapeHtml(combatData.narrative) + "</div>"
          : "") +
        "</div>",
      );
    }
    const skillChecks = (snap && snap.skill_checks) || data.skill_results || [];
    if (skillChecks.length > 0) {
      turnParts.push('<div class="turn-skills flex flex-wrap gap-1.5 px-1">' + renderSkillChips(skillChecks) + "</div>");
    }
    if (data.brief) {
      turnParts.push(
        '<div class="turn-brief px-3 py-2 text-xs text-gray-500 border-l-2 border-gray-700 bg-[#0f0f0f]/50 rounded-r">' +
        escapeHtml(data.brief) +
        "</div>",
      );
    }
    if (data.narrative) {
      turnParts.push(
        '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
        escapeHtml(data.narrative).replace(/\n/g, "<br>") +
        "</div>",
      );
    }
  }

  if (data.pending_interaction && data.pending_interaction.question) {
    if (!data.narrative || data.narrative.indexOf(data.pending_interaction.question) === -1) {
      turnParts.push(
        '<div class="pending-question px-3 py-2 text-sm text-aged-gold border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r">' +
        escapeHtml(data.pending_interaction.question) +
        "</div>",
      );
    }
  }

  if (turnParts.length === 0 && data.narrative_html) {
    turnParts.push(
      '<div class="turn-narrative px-4 py-3 text-sm text-parchment border-l-2 border-aged-gold bg-[#1a1410]/60 rounded-r narrative-flash leading-relaxed">' +
      escapeHtml(data.narrative_html).replace(/\n/g, "<br>") +
      "</div>",
    );
  }
  if (turnParts.length === 0) {
    turnParts.push('<div class="turn-empty text-sm text-gray-500 italic">（没有返回叙事内容）</div>');
  }

  const turnHtml = '<div class="turn-card space-y-2 pb-3 border-b border-gray-800/40">' + turnParts.join("") + "</div>";
  const outputArea = document.getElementById("turn-output");
  outputArea.innerHTML = turnHtml;
  outputArea.scrollTop = 0;
  addToHistory(userText, turnHtml);

  const summaryEl = document.getElementById("last-turn-summary");
  if (userText) {
    summaryEl.textContent = "> " + userText;
    summaryEl.classList.remove("hidden");
  }

  if (data.game_over) {
    const endingText = data.ending ? data.ending.name + ": " + data.ending.narrative : "游戏结束";
    setTimeout(function () {
      outputArea.insertAdjacentHTML(
        "beforeend",
        '<div class="turn-ending px-4 py-3 text-sm text-aged-gold border-l-2 border-aged-gold bg-[#1a1410]/80 mt-2">' +
        '<div class="font-bold mb-1">结局</div>' + escapeHtml(endingText) + "</div>",
      );
      document.getElementById("user-input").disabled = true;
      const sum = document.getElementById("last-turn-summary");
      if (sum) sum.classList.add("hidden");
    }, 500);
  }
}

async function runTurnRequest(fd, displayText, opts) {
  const input = document.getElementById("user-input");
  if (opts && opts.clearInput && input) input.value = "";
  if (input) input.disabled = true;
  const qa = document.getElementById("quick-actions");
  const qaBtns = qa ? qa.querySelectorAll("button") : [];
  qaBtns.forEach(function (b) { b.disabled = true; });
  const btnAction = document.getElementById("btn-action");
  if (btnAction) btnAction.disabled = true;
  const indicator = document.getElementById("step-indicator");
  if (indicator) indicator.innerHTML = '<span class="text-gray-500">思考中...</span>';
  try {
    const data = await postForm("/api/game/turn", fd);
    if (isHtmlFallback(data)) {
      document.getElementById("turn-output").innerHTML =
        '<div class="turn-card pb-3 border-b border-gray-800/40">' + data.html + "</div>";
      addToHistory(displayText, data.html);
    } else {
      handleTurnResponse(displayText, data);
    }
    try {
      const ps = await get("/api/game/player-status?format=json");
      if (ps && !isHtmlFallback(ps)) updateCharHUD(ps);
    } catch (e) { /* HUD 刷新失败不挡回合 */ }
  } catch (e) {
    const isHttp = typeof e.status === "number";
    const label = isHttp
      ? "服务器错误 (" + e.status + "): " + (e.body || "")
      : "网络错误: " + e.message;
    document.getElementById("turn-output").innerHTML =
      '<div class="turn-error px-3 py-2 text-sm text-red-400 border-l-2 border-red-500 bg-[#1a0a0a]/80">' +
      escapeHtml(label) +
      "</div>";
  }
  if (indicator) indicator.innerHTML = "";
  if (input) {
    input.disabled = false;
    input.focus();
  }
  qaBtns.forEach(function (b) { b.disabled = false; });
  if (btnAction) btnAction.disabled = false;
}

export async function sendTurn() {
  const input = document.getElementById("user-input");
  const text = input.value.trim();
  if (!text) return;
  const fd = new FormData();
  fd.append("user_input", text);
  await runTurnRequest(fd, text, { clearInput: true });
}

export async function sendTurnAction(actionType, actionTarget) {
  const fd = new FormData();
  fd.append("action_type", actionType);
  fd.append("user_input", "");
  let displayText = "搜索当前场景";
  if (actionTarget) {
    fd.append("action_target", actionTarget);
    displayText = "移动到 " + actionTarget;
  }
  await runTurnRequest(fd, displayText, { clearInput: false });
}

export function toggleDebug() {
  setSwitch("debug", !state.debug);
  paintSwitch(document.getElementById("btn-debug"), state.debug);
  location.reload();
}

export function toggleAutoWin() {
  setSwitch("autoWin", !state.autoWin);
  syncAutoWin();
}

export function syncAutoWin() {
  postJSON("/api/game/autowin", { enabled: state.autoWin }).catch(function () {});
  paintSwitch(document.getElementById("btn-autowin"), state.autoWin);
}
