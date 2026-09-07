import { get } from "./api.js";
import { state, setSwitch } from "./state.js";
import { escapeHtml } from "./util.js";
import { paintSwitch } from "./layout.js";

const EMPTY_TRACE = "本回合无流水（未开 debug 或尚未行动）";
const EMPTY_ENTITIES = "暂无实体可用性数据";
const EMPTY_SKILLS = "本回合无检定";
const EMPTY_LLM = "暂无 LLM 记录";

function setBody(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function flagSpan(ok, okLabel, failLabel) {
  return (
    '<span class="' + (ok ? "debug-ok" : "debug-fail") + '">' +
    (ok ? okLabel : failLabel) +
    "</span>"
  );
}

export function renderTrace(debug) {
  const evaluated = (debug && debug.evaluated) || [];
  const matched = (debug && debug.matched) || [];
  if (!evaluated.length && !matched.length) {
    return '<div class="debug-empty">' + EMPTY_TRACE + "</div>";
  }
  const rows = [];
  if (evaluated.length) {
    rows.push('<div class="debug-muted">评估</div>');
    for (const e of evaluated) {
      const ok = e.available !== false;
      rows.push(
        '<div class="debug-row">' +
        flagSpan(ok, "可用", "不可用") +
        " " + escapeHtml(e.id || "?") +
        (e.gate ? ' <span class="debug-muted">[' + escapeHtml(e.gate) + "]</span>" : "") +
        (e.reason ? " " + escapeHtml(e.reason) : "") +
        "</div>",
      );
    }
  }
  if (matched.length) {
    rows.push('<div class="debug-muted">匹配</div>');
    for (const e of matched) {
      const ok = e.success !== false;
      rows.push(
        '<div class="debug-row">' +
        flagSpan(ok, "成功", "失败") +
        " " + escapeHtml(e.id || "?") +
        (e.gate ? ' <span class="debug-muted">[' + escapeHtml(e.gate) + "]</span>" : "") +
        (e.reason ? " " + escapeHtml(e.reason) : "") +
        "</div>",
      );
    }
  }
  return rows.join("");
}

export function renderEntities(entities) {
  const list = entities || [];
  if (!list.length) {
    return '<div class="debug-empty">' + EMPTY_ENTITIES + "</div>";
  }
  return list.map(function (e) {
    const ok = e.available !== false;
    return (
      '<div class="debug-row">' +
      flagSpan(ok, "可用", "不可用") +
      " " + escapeHtml(e.id || "?") +
      (e.name ? " " + escapeHtml(e.name) : "") +
      (e.gate ? ' <span class="debug-muted">[' + escapeHtml(e.gate) + "]</span>" : "") +
      (e.reason ? " " + escapeHtml(e.reason) : "") +
      "</div>"
    );
  }).join("");
}

export function renderSkills(results) {
  const list = results || [];
  if (!list.length) {
    return '<div class="debug-empty">' + EMPTY_SKILLS + "</div>";
  }
  return list.map(function (sc) {
    const success = sc.success !== false;
    let extra = "";
    if (sc.raw_check) {
      extra += " " + escapeHtml(sc.raw_check);
    }
    if (sc.raw_roll != null && sc.raw_roll !== "") {
      extra += ' <span class="debug-muted">D100=' + escapeHtml(sc.raw_roll);
      if (sc.target != null && sc.target !== "") {
        extra += "/" + escapeHtml(sc.target);
      }
      extra += "</span>";
    }
    const enh = sc.enhancement && sc.enhancement.detail_override;
    if (enh) {
      extra += ' <span class="debug-muted">' + escapeHtml(enh) + "</span>";
    }
    return (
      '<div class="debug-row">' +
      flagSpan(success, "OK", "FAIL") +
      " " + escapeHtml(sc.entity_id || "?") +
      (sc.tier ? ' <span class="debug-muted">[' + escapeHtml(sc.tier) + "]</span>" : "") +
      extra +
      "</div>"
    );
  }).join("");
}

export function renderLlm(records) {
  const list = records || [];
  if (!list.length) {
    return '<div class="debug-empty">' + EMPTY_LLM + "</div>";
  }
  return list.map(function (r) {
    const name = escapeHtml(r.filename || r.name || "?");
    const body = escapeHtml(r.full || r.preview || r.text || "");
    return (
      '<details class="debug-llm-item">' +
      "<summary>" + name + "</summary>" +
      '<pre class="debug-llm-preview">' + body + "</pre>" +
      "</details>"
    );
  }).join("");
}

function pickSkills(data) {
  const results = data.skill_results;
  if (Array.isArray(results) && results.length) return results;
  const checks = data.player_snapshot && data.player_snapshot.skill_checks;
  if (Array.isArray(checks) && checks.length) return checks;
  return [];
}

export function applyTurnDebug(data) {
  if (!data) return;
  if (data.debug) {
    setBody("debug-trace-body", renderTrace(data.debug));
  }
  const skills = pickSkills(data);
  const hasResults = Array.isArray(data.skill_results);
  const hasChecks = !!(data.player_snapshot && Array.isArray(data.player_snapshot.skill_checks));
  if (data.debug || skills.length || hasResults || hasChecks) {
    setBody("debug-skills-body", renderSkills(skills));
  }
}

export function applyDebugSnapshot(data) {
  if (!data || data.html) return;
  if (Array.isArray(data.scene_entities)) {
    setBody("debug-entities-body", renderEntities(data.scene_entities));
  }
  if (Array.isArray(data.llm_records)) {
    setBody("debug-llm-body", renderLlm(data.llm_records));
  }
}

export async function refreshDebugSnapshot() {
  try {
    const data = await get("/api/game/debug?turns=5");
    if (!data || data.html || data.error) return data;
    applyDebugSnapshot(data);
    return data;
  } catch {
    /* debug 拉取失败不挡主流程 */
  }
}

export function syncDebugUi() {
  const on = !!state.debug;
  const panel = document.getElementById("debug-panel");
  if (panel) {
    panel.classList.toggle("hidden", !on);
    panel.setAttribute("aria-hidden", on ? "false" : "true");
  }
  const badge = document.getElementById("debug-badge");
  if (badge) badge.classList.toggle("hidden", !on);
  paintSwitch(document.getElementById("btn-debug"), on);
}

export function toggleDebug() {
  setSwitch("debug", !state.debug);
  syncDebugUi();
  if (state.debug) return refreshDebugSnapshot();
}
