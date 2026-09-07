import { escapeHtml, isHtmlFallback } from "./util.js";
import { get } from "./api.js";

const STAT_LABELS = {
  STR: "力量", CON: "体质", SIZ: "体型", DEX: "敏捷", APP: "外貌",
  INT: "智力", POW: "意志", EDU: "教育", LUCK: "幸运",
};
const STAT_KEYS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"];
const CAT_ORDER = ["战斗", "操作", "感知", "知识", "社交", "其他"];
const CAT_COLORS = {
  战斗: "text-red-400/70",
  操作: "text-blue-400/70",
  感知: "text-green-400/70",
  知识: "text-purple-400/70",
  社交: "text-yellow-400/70",
  其他: "text-gray-500",
};

export function hpBarPercent(hp, hpMax) {
  const max = Number(hpMax) || 0;
  const v = Number(hp) || 0;
  return Math.min(100, Math.max(0, max ? (v / max * 100) : 0));
}

export function sanBarPercent(san, sanMax) {
  const v = Number(san) || 0;
  const max = Math.max(1, Number(sanMax) || 0);
  return Math.min(100, Math.max(0, (v / max) * 100));
}

function avatarBlock(url) {
  const raw = String(url || "").replace(/"/g, "");
  if (raw && !/^\s*javascript:/i.test(raw)) {
    return (
      '<img src="' + escapeHtml(raw) +
      '" class="w-14 h-14 rounded-full object-cover border-2 border-gray-700" onerror="this.style.display=\'none\'">'
    );
  }
  return (
    '<div class="w-14 h-14 rounded-full bg-gray-800 flex items-center justify-center text-gray-500 border-2 border-gray-700">' +
    '<svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>' +
    "</div>"
  );
}

function renderSkills(skills) {
  const list = Array.isArray(skills) ? skills : [];
  if (!list.length) return "";
  const cats = {};
  list.forEach(function (s) {
    const cat = s.category || "其他";
    (cats[cat] || (cats[cat] = [])).push(s);
  });
  const ordered = [];
  const seen = {};
  CAT_ORDER.forEach(function (cat) {
    if (cats[cat]) {
      ordered.push(cat);
      seen[cat] = true;
    }
  });
  Object.keys(cats).forEach(function (cat) {
    if (!seen[cat]) ordered.push(cat);
  });
  const sections = ordered.map(function (cat) {
    const items = cats[cat].slice().sort(function (a, b) { return (b.value || 0) - (a.value || 0); });
    const color = CAT_COLORS[cat] || "text-gray-500";
    const rows = items.map(function (s) {
      return (
        '<div class="flex justify-between items-center py-0.5">' +
        '<span class="text-xs text-gray-400">' + escapeHtml(s.name) + "</span>" +
        '<span class="text-xs font-mono ' + color + '">' + escapeHtml(s.value) + "%</span>" +
        "</div>"
      );
    }).join("");
    return (
      '<details class="group">' +
      '<summary class="flex items-center justify-between cursor-pointer py-1 text-[10px] text-gray-500 hover:text-gray-300 list-none">' +
      '<span class="flex items-center gap-1"><span class="w-1 h-1 rounded-full ' + color + '"></span>' +
      escapeHtml(cat) + " (" + items.length + ")</span>" +
      '<span class="text-gray-600 group-open:rotate-180 transition-transform">▼</span>' +
      "</summary>" +
      '<div class="pl-3 border-l border-gray-800/40 ml-1 space-y-0.5">' + rows + "</div>" +
      "</details>"
    );
  }).join("");
  return (
    '<div class="pt-2 border-t border-gray-800/60">' +
    '<div class="text-[10px] text-gray-500 font-bold mb-1.5">技能 (' + list.length + ")</div>" +
    '<div class="space-y-1">' + sections + "</div></div>"
  );
}

export function renderCharacterCard(data) {
  if (!data || data.name == null) {
    return '<span class="text-gray-500">无调查员</span>';
  }
  const stats = data.stats || {};
  const hpPct = hpBarPercent(data.hp, data.hp_max);
  const sanPct = sanBarPercent(data.san, data.san_max);
  const age = data.age != null && data.age !== "" ? escapeHtml(data.age) + "岁" : "";
  const header = (
    '<div class="flex items-center gap-3 pb-3 border-b border-gray-800/60">' +
    avatarBlock(data.avatar_url) +
    '<div class="min-w-0">' +
    '<div class="text-sm font-bold text-aged-gold truncate">' + escapeHtml(data.name) + "</div>" +
    '<div class="text-[10px] text-gray-500">' +
    [age, escapeHtml(data.gender), escapeHtml(data.occupation)].filter(Boolean).join(" ") +
    "</div></div></div>"
  );

  const introParts = [];
  if (data.appearance) {
    introParts.push(
      '<div class="text-[10px] text-gray-400"><span class="text-gray-500">外貌：</span>' +
      escapeHtml(data.appearance) + "</div>",
    );
  }
  if (data.personal_description) {
    introParts.push(
      '<div class="text-[10px] text-gray-400 leading-relaxed">' +
      escapeHtml(data.personal_description) + "</div>",
    );
  }
  const intro = introParts.length
    ? '<div class="space-y-1.5 pt-2">' + introParts.join("") + "</div>"
    : "";

  const statsCells = STAT_KEYS.map(function (k) {
    return (
      '<div class="text-center p-1.5 bg-[#1a150c]/60 rounded border border-gray-800/40">' +
      '<div class="text-[10px] text-gray-500">' + (STAT_LABELS[k] || k) + "</div>" +
      '<div class="text-sm font-bold text-gray-300">' + escapeHtml(stats[k] ?? 0) + "</div>" +
      "</div>"
    );
  }).join("");
  const statsHtml = (
    '<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">属性</div>' +
    '<div class="grid grid-cols-3 gap-1.5">' + statsCells + "</div></div>"
  );

  const derivedHtml = (
    '<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">状态</div>' +
    '<div class="space-y-2">' +
    '<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>HP</span>' +
    '<span class="text-coc-green">' + escapeHtml(data.hp) + "/" + escapeHtml(data.hp_max) + "</span></div>" +
    '<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-coc-green rounded transition-all duration-500" style="width:' + hpPct + '%"></div></div></div>' +
    '<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>SAN</span>' +
    '<span class="text-aged-gold">' + escapeHtml(data.san) + "</span></div>" +
    '<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-aged-gold rounded transition-all duration-500" style="width:' + sanPct + '%"></div></div></div>' +
    '<div class="flex gap-3 text-[10px] text-gray-400 pt-1">' +
    '<span>MP <span class="text-gray-300">' + escapeHtml(data.mp) + "/" + escapeHtml(data.mp_max) + "</span></span>" +
    '<span>MOV <span class="text-gray-300">' + escapeHtml(data.mov) + "</span></span>" +
    '<span>DB <span class="text-gray-300">' + escapeHtml(data.db) + "</span></span>" +
    '<span>BUILD <span class="text-gray-300">' + escapeHtml(data.build) + "</span></span>" +
    '<span>DODGE <span class="text-gray-300">' + escapeHtml(data.dodge) + "</span></span>" +
    "</div></div></div>"
  );

  const weapons = Array.isArray(data.weapons) ? data.weapons : [];
  const weaponsHtml = weapons.length
    ? (
      '<div class="pt-2 border-t border-gray-800/60">' +
      '<div class="text-[10px] text-gray-500 font-bold mb-1.5">武器 (' + weapons.length + ")</div>" +
      '<div class="space-y-1">' +
      weapons.map(function (w) {
        return (
          '<div class="flex justify-between text-xs text-gray-400 py-0.5">' +
          "<span>" + escapeHtml(w.name) + '</span><span class="text-gray-500">' +
          escapeHtml(w.damage) + "</span></div>"
        );
      }).join("") +
      "</div></div>"
    )
    : "";

  const spells = Array.isArray(data.spells) ? data.spells : [];
  const spellsHtml = spells.length
    ? (
      '<div class="pt-2 border-t border-gray-800/60">' +
      '<div class="text-[10px] text-gray-500 font-bold mb-1.5">已知法术 (' + spells.length + ")</div>" +
      '<div class="space-y-0.5">' +
      spells.map(function (sp) {
        const cat = sp.category ? escapeHtml(sp.category) : "库中未找到";
        const catCls = sp.category ? "text-gray-500 text-[10px]" : "text-[10px]";
        const nameCls = sp.category ? "text-xs text-gray-400" : "text-xs text-gray-500";
        return (
          '<div class="flex justify-between ' + nameCls + ' py-0.5">' +
          "<span>" + escapeHtml(sp.name) + "</span>" +
          '<span class="' + catCls + '">' + cat + "</span></div>"
        );
      }).join("") +
      "</div></div>"
    )
    : "";

  const itemsHtml = (
    '<div class="pt-2 border-t border-gray-800/60">' +
    '<div class="text-[10px] text-gray-500 font-bold mb-1.5">物品</div>' +
    '<div class="text-xs text-gray-400 leading-relaxed">' +
    escapeHtml(data.items || "无").replace(/\n/g, "<br>") +
    "</div></div>"
  );

  return header + intro + statsHtml + derivedHtml + renderSkills(data.skills)
    + weaponsHtml + spellsHtml + itemsHtml;
}

export async function toggleCharCard() {
  const expanded = document.getElementById("char-panel-expanded");
  if (!expanded) return;
  if (expanded.classList.contains("hidden")) {
    try {
      const data = await get("/api/game/character-card");
      if (isHtmlFallback(data)) {
        expanded.textContent = "角色卡加载失败";
      } else {
        expanded.innerHTML = renderCharacterCard(data);
      }
    } catch (e) {
      expanded.textContent = "角色卡加载失败";
    }
    expanded.classList.remove("hidden");
  } else {
    expanded.classList.add("hidden");
  }
}

export function updateCharHUD(data) {
  if (!data) return;
  const hp = data.hp || 0;
  const hpMax = data.hp_max || hp || 10;
  const san = data.san || 0;
  const sanMax = data.san_max || 99;
  const nameEl = document.getElementById("char-name");
  if (nameEl) nameEl.textContent = data.name || "调查员";
  const hpText = document.getElementById("char-hp-text");
  if (hpText) hpText.textContent = hp + "/" + hpMax;
  const sanText = document.getElementById("char-san-text");
  if (sanText) sanText.textContent = san;
  const hpBar = document.getElementById("char-hp-bar");
  if (hpBar) hpBar.style.width = hpBarPercent(hp, hpMax) + "%";
  const sanBar = document.getElementById("char-san-bar");
  if (sanBar) sanBar.style.width = (san > 0 ? sanBarPercent(san, sanMax) : 0) + "%";
  if (data.mp !== undefined && data.mp !== null) {
    const mp = data.mp || 0;
    const mpMax = data.mp_max || mp || 1;
    const mpText = document.getElementById("char-mp-text");
    if (mpText) mpText.textContent = mp + "/" + mpMax;
    const mpBar = document.getElementById("char-mp-bar");
    if (mpBar) mpBar.style.width = (mpMax > 0 ? (mp / mpMax * 100) : 0) + "%";
  }
  if (data.known_spells !== undefined && data.known_spells !== null) {
    const spellsEl = document.getElementById("char-spells");
    if (spellsEl) {
      if (data.known_spells.length) {
        const label = "法术 · " + data.known_spells.join(" / ");
        spellsEl.textContent = label;
        spellsEl.title = label;
        spellsEl.style.display = "";
      } else {
        spellsEl.style.display = "none";
      }
    }
  }
  if (data.avatar_url) {
    const avatar = document.getElementById("char-avatar");
    if (avatar) {
      const url = String(data.avatar_url).replace(/"/g, "");
      if (!/^\s*javascript:/i.test(url)) {
        avatar.innerHTML =
          '<img src="' + escapeHtml(url) +
          '" class="w-12 h-12 rounded-full object-cover" onerror="this.parentElement.innerHTML=\'<svg class=\\\'w-6 h-6\\\' fill=\\\'none\\\' stroke=\\\'currentColor\\\' viewBox=\\\'0 0 24 24\\\'><path stroke-linecap=\\\'round\\\' stroke-linejoin=\\\'round\\\' stroke-width=\\\'1.5\\\' d=\\\'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z\\\'/></svg>\'">';
      }
    }
  }
  const occ = document.getElementById("char-occupation");
  if (occ) occ.textContent = data.occupation || data.name || "--";
}
