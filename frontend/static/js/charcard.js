import { escapeHtml } from "./util.js";

export function toggleCharCard() {
  const expanded = document.getElementById("char-panel-expanded");
  if (!expanded) return;
  if (expanded.classList.contains("hidden")) {
    if (typeof htmx !== "undefined") {
      htmx.ajax("GET", "/api/game/character-card", "#char-panel-expanded");
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
  if (hpBar) hpBar.style.width = (hpMax > 0 ? (hp / hpMax * 100) : 0) + "%";
  const sanBar = document.getElementById("char-san-bar");
  if (sanBar) sanBar.style.width = (san > 0 ? (san / Math.max(1, sanMax) * 100) : 0) + "%";
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
