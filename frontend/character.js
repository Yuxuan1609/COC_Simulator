// character.js — COC 7th 车卡模拟器
// 纯静态，无框架依赖。角色数据全程存于 builderState，最后一步导出 JSON。

(function() {
'use strict';

// ═══════════════════════════════════════════
//  State
// ═══════════════════════════════════════════

const builderState = {
    currentStep: 1,
    manualMode: false,
    occupations: [],
    skills: [],
    weapons: [],
    equipment: [],
    statRolls: {
        STR: { dice: 3, mod: 0, mul: 5 }, CON: { dice: 3, mod: 0, mul: 5 },
        DEX: { dice: 3, mod: 0, mul: 5 }, APP: { dice: 3, mod: 0, mul: 5 },
        POW: { dice: 3, mod: 0, mul: 5 },
        SIZ: { dice: 2, mod: 6, mul: 5 }, INT: { dice: 2, mod: 6, mul: 5 },
        EDU: { dice: 2, mod: 6, mul: 5 }, LUCK: { dice: 3, mod: 0, mul: 5 },
    },
};

// ═══════════════════════════════════════════
//  Dice
// ═══════════════════════════════════════════

function rollD6(n) {
    let sum = 0;
    const arr = new Uint32Array(n);
    crypto.getRandomValues(arr);
    for (let i = 0; i < n; i++) sum += (arr[i] % 6) + 1;
    return sum;
}

// ═══════════════════════════════════════════
//  Derived stats
// ═══════════════════════════════════════════

function calcDerived(stats, age) {
    const CON = stats.CON || 0, SIZ = stats.SIZ || 0, POW = stats.POW || 0;
    const DEX = stats.DEX || 0, STR = stats.STR || 0;
    const HP = Math.floor((CON + SIZ) / 10);
    const MP = Math.floor(POW / 5);
    const DODGE = Math.floor(DEX / 2);
    let MOV = 8;
    if (STR < SIZ && DEX < SIZ) MOV = 7;
    else if (STR > SIZ && DEX > SIZ) MOV = 9;
    const ss = STR + SIZ;
    let DB = '0', BUILD = 0;
    if (ss <= 64) { DB = '-2'; BUILD = -2; }
    else if (ss <= 84) { DB = '-1'; BUILD = -1; }
    else if (ss <= 124) { DB = '0'; BUILD = 0; }
    else if (ss <= 164) { DB = '+1D4'; BUILD = 1; }
    else if (ss <= 204) { DB = '+1D6'; BUILD = 2; }
    else { DB = '+2D6'; BUILD = 3; }
    return { HP, MP, SAN: POW, SAN_MAX: 99, MOV, DB, BUILD, DODGE };
}

// ═══════════════════════════════════════════
//  Step navigation
// ═══════════════════════════════════════════

function setStep(n) {
    document.querySelectorAll('.panel').forEach(el => el.classList.remove('active'));
    const panel = document.getElementById('step-' + n);
    if (panel) panel.classList.add('active');
    document.querySelectorAll('#progress .step').forEach(el => {
        el.classList.remove('active');
        if (parseInt(el.dataset.step) === n) el.classList.add('active');
    });
    builderState.currentStep = n;
}

window.nextStep = function() {
    const s = builderState.currentStep;
    if (s === 1) collectPersonal();
    if (s === 2) collectStats();
    if (s === 3) collectSkills();
    if (s === 4) collectCombat();
    if (s === 5) return;
    if (s === 2) renderSkills();
    if (s === 3) renderStep4();
    if (s === 4) renderSummary();
    setStep(s + 1);
};

window.prevStep = function() {
    if (builderState.currentStep > 1) setStep(builderState.currentStep - 1);
};

// ═══════════════════════════════════════════
//  LLM 描述生成
// ═══════════════════════════════════════════

const API_BASE = 'http://localhost:8080';
const LLM_TRIGGER = '/llm';

/**
 * 检测 textarea 输入是否以 /llm 结尾，若是则触发 LLM 生成。
 * 绑定到 input 事件，每次按键后检查。
 */
function onLlmTextareaInput(e) {
    const textarea = e.target;
    const value = textarea.value.trim();

    // 清除上一次的触发标记（允许重复触发）
    if (textarea.dataset.llmFired === 'true' && !value.endsWith(LLM_TRIGGER)) {
        textarea.dataset.llmFired = 'false';
    }

    // 检测触发条件
    if (!value.endsWith(LLM_TRIGGER)) return;
    if (textarea.dataset.llmFired === 'true') return;

    textarea.dataset.llmFired = 'true';

    // 提取用户提示词（去掉末尾 /llm）
    const userPrompt = value.slice(0, -LLM_TRIGGER.length).trim();
    if (!userPrompt) return;

    // 根据 textarea id 确定字段类型
    const fieldType = textarea.id === 'char-appearance' ? 'appearance' : 'description';

    generateDescription(textarea, fieldType, userPrompt);
}

/**
 * 调用后端 API 生成描述。
 */
function generateDescription(textarea, fieldType, userPrompt) {
    // 显示加载状态
    textarea.classList.add('llm-loading');
    textarea.placeholder = '生成中...';
    textarea.disabled = true;

    fetch(API_BASE + '/api/generate-description', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: fieldType, prompt: userPrompt }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) {
            console.error('LLM 生成失败:', data.error);
            textarea.value = userPrompt + ' [生成失败: ' + data.error + ']';
        } else {
            textarea.value = data.text || '';
        }
    })
    .catch(function(err) {
        console.error('API 调用失败:', err);
        textarea.value = userPrompt + ' [API 不可用，请确认服务器已启动: python frontend/server.py]';
    })
    .finally(function() {
        textarea.classList.remove('llm-loading');
        textarea.placeholder = '简要描述外貌特征...';
        textarea.disabled = false;
        textarea.dataset.llmFired = 'false';
        textarea.focus();
    });
}

// ═══════════════════════════════════════════
//  Step 1: Personal info
// ═══════════════════════════════════════════

function collectPersonal() {
    builderState.name = document.getElementById('char-name').value.trim() || 'Unknown';
    builderState.age = parseInt(document.getElementById('char-age').value) || 20;
    builderState.gender = document.getElementById('char-gender').value;
    builderState.appearance = document.getElementById('char-appearance').value.trim();
    builderState.description = document.getElementById('char-description').value.trim();
}

// ═══════════════════════════════════════════
//  Step 2: Stats
// ═══════════════════════════════════════════

window.rollAllStats = function() {
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    names.forEach(name => {
        const cfg = builderState.statRolls[name];
        const val = (rollD6(cfg.dice) + cfg.mod) * cfg.mul;
        builderState[name] = val;
        const card = document.getElementById('stat-' + name);
        if (card) {
            card.querySelector('.stat-value').textContent = val;
            card.querySelector('.stat-value-input').value = val;
        }
    });
    renderDerived();
};

function collectStats() {
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    names.forEach(name => {
        const card = document.getElementById('stat-' + name);
        if (!card) return;
        if (builderState.manualMode) {
            builderState[name] = parseInt(card.querySelector('.stat-value-input').value) || 0;
        } else {
            builderState[name] = parseInt(card.querySelector('.stat-value').textContent) || 0;
        }
    });
}

window.toggleManualInput = function() {
    builderState.manualMode = !builderState.manualMode;
    document.querySelectorAll('.stat-card').forEach(c => {
        c.classList.toggle('manual', builderState.manualMode);
    });
};

function renderDerived() {
    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(n => {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    Object.assign(builderState, { derived: d });
    const el = document.getElementById('derived-display');
    if (!el) return;
    el.innerHTML = [
        ['HP', d.HP], ['MP', d.MP], ['SAN', d.SAN], ['SAN_MAX', d.SAN_MAX],
        ['MOV', d.MOV], ['DB', d.DB], ['BUILD', d.BUILD], ['DODGE', d.DODGE],
    ].map(([label, val]) =>
        '<div class="derived-item"><div class="derived-label">' + label + '</div><div class="derived-value">' + val + '</div></div>'
    ).join('');
}

// ═══════════════════════════════════════════
//  Step 3: Skills
// ═══════════════════════════════════════════

function collectSkills() {
    const rows = document.querySelectorAll('.skill-row');
    builderState.skills = [];
    rows.forEach(row => {
        const nameEl = row.querySelector('.skill-name');
        const valEl = row.querySelector('.skill-value');
        const baseEl = row.querySelector('.skill-base');
        const name = nameEl.textContent.replace(/^● /, '');
        builderState.skills.push({
            name: name,
            base_value: parseInt(baseEl.textContent) || 0,
            value: parseInt(valEl.value) || parseInt(valEl.textContent) || 0,
            category: row.dataset.category || '通用',
            is_occupation: row.classList.contains('occupation'),
        });
    });
}

function renderSkills() {
    const container = document.getElementById('skills-display');
    if (!container) return;
    const occSelect = document.getElementById('occ-select');
    const occName = occSelect ? occSelect.options[occSelect.selectedIndex].text : '';
    const occData = builderState.occupations.find(o => o.name === occName);
    const occSkills = occData ? occData.occupation_skills : [];

    const stats = { EDU: builderState.EDU || 0, DEX: builderState.DEX || 0, APP: builderState.APP || 0, INT: builderState.INT || 0, ...builderState };
    const formula = occData ? occData.skill_points_formula : 'EDU*4';
    let occPoints = parseFormula(formula, stats);
    let intPoints = (stats.INT || 0) * 2;
    builderState.occPointsRemaining = occPoints;
    builderState.intPointsRemaining = intPoints;

    document.getElementById('occ-desc').textContent = occData ? occData.description : '';
    document.getElementById('occ-formula').textContent = formula + ' = ' + occPoints;
    document.getElementById('occ-points').textContent = occPoints;
    document.getElementById('int-points').textContent = intPoints;

    if (!builderState._skillsInitialized) {
        builderState.skills = [];
        SKILL_BASE_VALUES.forEach(function(item) {
            builderState.skills.push({
                name: item.name,
                base_value: item.base,
                value: item.base,
                category: item.category,
                is_occupation: occSkills.includes(item.name),
            });
        });
        builderState._skillsInitialized = true;
    }

    container.innerHTML = builderState.skills.map(function(s, idx) {
        const isOcc = occSkills.includes(s.name);
        const cls = isOcc ? 'skill-row occupation' : 'skill-row';
        return '<div class="' + cls + '" data-idx="' + idx + '" data-category="' + s.category + '">'
            + '<span class="skill-name">' + s.name + '</span>'
            + '<span class="skill-category">' + s.category + '</span>'
            + '<span class="skill-base">' + s.base_value + '</span>'
            + '<button class="skill-btn" onclick="adjustSkill(' + idx + ', -5)">&#x2212;</button>'
            + '<input class="skill-value" value="' + s.value + '" onchange="onSkillChange(' + idx + ', this)">'
            + '<button class="skill-btn" onclick="adjustSkill(' + idx + ', 5)">+</button>'
            + '</div>';
    }).join('');
}

window.adjustSkill = function(idx, delta) {
    const sk = builderState.skills[idx];
    const newVal = Math.max(0, Math.min(99, sk.value + delta));
    updateSkillValue(idx, newVal);
};

window.onSkillChange = function(idx, input) {
    const newVal = Math.max(0, Math.min(99, parseInt(input.value) || 0));
    updateSkillValue(idx, newVal);
};

function updateSkillValue(idx, newVal) {
    const sk = builderState.skills[idx];
    const oldVal = sk.value;
    const cost = newVal - oldVal;
    if (cost > 0) {
        if (sk.is_occupation) {
            if (builderState.occPointsRemaining < cost) return;
            builderState.occPointsRemaining -= cost;
        } else {
            if (builderState.intPointsRemaining < cost) return;
            builderState.intPointsRemaining -= cost;
        }
    } else {
        if (sk.is_occupation) builderState.occPointsRemaining -= cost;
        else builderState.intPointsRemaining -= cost;
    }
    sk.value = newVal;
    document.getElementById('occ-points').textContent = builderState.occPointsRemaining;
    document.getElementById('int-points').textContent = builderState.intPointsRemaining;
    const input = document.querySelector('.skill-row[data-idx="' + idx + '"] .skill-value');
    if (input) input.value = newVal;
}

function parseFormula(formula, stats) {
    try {
        let result = 0;
        const parts = formula.replace('-', '+-').split('+');
        parts.forEach(function(part) {
            part = part.trim();
            if (!part) return;
            if (part.indexOf('*') !== -1) {
                const [attr, mul] = part.split('*');
                result += (stats[attr.trim().toUpperCase()] || 0) * parseInt(mul);
            } else {
                result += stats[part.trim().toUpperCase()] || 0;
            }
        });
        return result;
    } catch(e) { return (stats.EDU || 0) * 4; }
}

// ═══════════════════════════════════════════
//  Step 4: Combat & Equipment
// ═══════════════════════════════════════════

function renderStep4() {
    renderWeapons();
    renderEquipment();
}

function renderWeapons() {
    if (builderState.weapons.length === 0) {
        builderState.weapons.push({ name: '徒手', skill_name: '格斗', damage: '1D3+DB', range: '接触', ammo: 0, malfunction: 100 });
    }
    const container = document.getElementById('weapons-list');
    container.innerHTML = builderState.weapons.map(function(w, i) {
        return '<div class="weapon-row">'
            + '<input value="' + esc(w.name) + '" onchange="wpnSet(' + i + ', \'name\', this.value)" placeholder="武器名">'
            + '<input value="' + esc(w.skill_name) + '" onchange="wpnSet(' + i + ', \'skill_name\', this.value)" placeholder="技能" class="short">'
            + '<input value="' + esc(w.damage) + '" onchange="wpnSet(' + i + ', \'damage\', this.value)" placeholder="伤害" class="short">'
            + '<input value="' + esc(w.range) + '" onchange="wpnSet(' + i + ', \'range\', this.value)" placeholder="射程" class="short">'
            + '<button class="remove-btn" onclick="removeWeapon(' + i + ')">&#x2715;</button>'
            + '</div>';
    }).join('');
}

window.wpnSet = function(i, key, val) { builderState.weapons[i][key] = val; };

window.addWeapon = function() {
    builderState.weapons.push({ name: '', skill_name: '格斗', damage: '1D6', range: '接触', ammo: 0, malfunction: 100 });
    renderWeapons();
};

window.removeWeapon = function(i) {
    builderState.weapons.splice(i, 1);
    renderWeapons();
};

function renderEquipment() {
    const container = document.getElementById('equipment-list');
    container.innerHTML = builderState.equipment.map(function(item, i) {
        return '<div class="item-row"><span class="item-name">' + esc(item) + '</span>'
            + '<button class="remove-btn" onclick="removeEquip(' + i + ')">&#x2715;</button></div>';
    }).join('');
}

window.removeEquip = function(i) {
    builderState.equipment.splice(i, 1);
    renderEquipment();
};

function collectCombat() {
    builderState.weapons = builderState.weapons.filter(function(w) { return w.name.trim(); });
}

// Equipment input handler
document.addEventListener('DOMContentLoaded', function() {
    const equipInput = document.getElementById('equip-input');
    if (equipInput) {
        equipInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && this.value.trim()) {
                builderState.equipment.push(this.value.trim());
                this.value = '';
                renderEquipment();
            }
        });
    }
    // Occupation change handler
    const occSelect = document.getElementById('occ-select');
    if (occSelect) {
        occSelect.addEventListener('change', function() {
            builderState._skillsInitialized = false;
            renderSkills();
        });
    }
    // LLM 描述生成：绑定 /llm 触发器
    var appearanceTextarea = document.getElementById('char-appearance');
    var descriptionTextarea = document.getElementById('char-description');
    if (appearanceTextarea) {
        appearanceTextarea.addEventListener('input', onLlmTextareaInput);
    }
    if (descriptionTextarea) {
        descriptionTextarea.addEventListener('input', onLlmTextareaInput);
    }

    // Init
    loadOccupations();
    renderStatsCards();
    renderDerived();
});

function renderStatsCards() {
    const container = document.getElementById('stats-display');
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    const labels = { STR:'力量', CON:'体质', SIZ:'体型', DEX:'敏捷', APP:'外貌', INT:'智力', POW:'意志', EDU:'教育', LUCK:'幸运' };
    container.innerHTML = names.map(function(name) {
        return '<div class="stat-card" id="stat-' + name + '">'
            + '<div class="stat-name">' + labels[name] + ' (' + name + ')</div>'
            + '<div class="stat-value">0</div>'
            + '<input class="stat-value-input" value="0">'
            + '</div>';
    }).join('');
}

// ═══════════════════════════════════════════
//  Step 5: Export
// ═══════════════════════════════════════════

function renderSummary() {
    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(function(n) {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    builderState.derived = d;

    const occSelect = document.getElementById('occ-select');
    const occName = occSelect ? occSelect.options[occSelect.selectedIndex].text : '';

    const summary = '调查员: ' + (builderState.name || '?') + '\n'
        + '职业: ' + occName + ' | 年龄: ' + (builderState.age || '?') + '\n'
        + 'HP: ' + d.HP + ' | MP: ' + d.MP + ' | SAN: ' + d.SAN + ' | MOV: ' + d.MOV + '\n'
        + 'DB: ' + d.DB + ' | BUILD: ' + d.BUILD + ' | DODGE: ' + d.DODGE + '\n'
        + '技能数: ' + (builderState.skills.length) + ' | 武器: ' + builderState.weapons.length + ' | 装备: ' + builderState.equipment.length;
    document.getElementById('summary-display').textContent = summary;
}

window.exportJSON = function() {
    collectPersonal();
    collectStats();
    collectSkills();
    collectCombat();
    builderState.backstory = document.getElementById('char-backstory').value.trim();

    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(function(n) {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    builderState.derived = d;

    const occName = document.getElementById('occ-select').options[document.getElementById('occ-select').selectedIndex].text;
    const occData = builderState.occupations.find(function(o) { return o.name === occName; });

    const data = {
        meta: { version: '1.0', created_at: new Date().toISOString(), rules_edition: 'COC7' },
        personal: {
            name: builderState.name || 'Unknown',
            age: builderState.age || 20,
            gender: builderState.gender || '',
            occupation: occData || null,
            description: builderState.description || '',
            appearance: builderState.appearance || '',
        },
        stats: stats,
        derived: d,
        skills: (builderState.skills || []).map(function(s) {
            return {
                name: s.name, base: s.base_value, value: s.value,
                category: s.category, is_occupation: s.is_occupation,
            };
        }),
        combat: { weapons: builderState.weapons || [] },
        equipment: builderState.equipment || [],
        backstory: builderState.backstory || '',
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = (builderState.name || 'character') + '_character.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
};

// ═══════════════════════════════════════════
//  Occupations loader
// ═══════════════════════════════════════════

function loadOccupations() {
    fetch('../data/occupations.json')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            builderState.occupations = data;
            const sel = document.getElementById('occ-select');
            data.forEach(function(o) {
                const opt = document.createElement('option');
                opt.value = o.name;
                opt.textContent = o.name;
                sel.appendChild(opt);
            });
        })
        .catch(function() {
            // Fallback: hard-coded basic occupations
            builderState.occupations = [
                { name: '学生', description: '', occupation_skills: ['图书馆使用','外语','母语','历史','科学','心理学'], skill_points_formula: 'EDU*4', credit_rating_min: 5, credit_rating_max: 10 },
                { name: '私家侦探', description: '', occupation_skills: ['侦查','追踪','图书馆使用','心理学','法律','潜行','格斗'], skill_points_formula: 'EDU*2+DEX*2', credit_rating_min: 10, credit_rating_max: 30 },
                { name: '医生', description: '', occupation_skills: ['急救','医学','心理学','精神分析','科学','说服'], skill_points_formula: 'EDU*4', credit_rating_min: 30, credit_rating_max: 80 },
                { name: '教授', description: '', occupation_skills: ['图书馆使用','母语','外语','历史','考古学','神秘学','心理学','说服'], skill_points_formula: 'EDU*4', credit_rating_min: 20, credit_rating_max: 70 },
                { name: '记者', description: '', occupation_skills: ['图书馆使用','聆听','说服','心理学','母语','潜行'], skill_points_formula: 'EDU*2+APP*2', credit_rating_min: 5, credit_rating_max: 50 },
            ];
            const sel = document.getElementById('occ-select');
            builderState.occupations.forEach(function(o) {
                const opt = document.createElement('option');
                opt.value = o.name;
                opt.textContent = o.name;
                sel.appendChild(opt);
            });
        });
}

// ═══════════════════════════════════════════
//  Skill base values (mirror of rules.py)
// ═══════════════════════════════════════════

const SKILL_BASE_VALUES = [
    { name: '会计', base: 5, category: '知识' }, { name: '人类学', base: 1, category: '知识' },
    { name: '估价', base: 5, category: '知识' }, { name: '考古学', base: 1, category: '知识' },
    { name: '魅惑', base: 15, category: '社交' }, { name: '攀爬', base: 20, category: '操作' },
    { name: '计算机使用', base: 5, category: '知识' }, { name: '信用评级', base: 0, category: '社交' },
    { name: '克苏鲁神话', base: 0, category: '知识' }, { name: '乔装', base: 5, category: '社交' },
    { name: '汽车驾驶', base: 20, category: '操作' }, { name: '电气维修', base: 10, category: '操作' },
    { name: '电子学', base: 1, category: '知识' }, { name: '话术', base: 5, category: '社交' },
    { name: '格斗', base: 25, category: '战斗' }, { name: '枪械', base: 20, category: '战斗' },
    { name: '急救', base: 30, category: '操作' }, { name: '历史', base: 5, category: '知识' },
    { name: '恐吓', base: 15, category: '社交' }, { name: '跳跃', base: 20, category: '操作' },
    { name: '外语', base: 1, category: '知识' }, { name: '母语', base: 50, category: '知识' },
    { name: '法律', base: 5, category: '知识' }, { name: '图书馆使用', base: 20, category: '知识' },
    { name: '聆听', base: 20, category: '感知' }, { name: '锁匠', base: 1, category: '操作' },
    { name: '机械维修', base: 10, category: '操作' }, { name: '医学', base: 1, category: '知识' },
    { name: '博物学', base: 10, category: '知识' }, { name: '导航', base: 10, category: '知识' },
    { name: '神秘学', base: 5, category: '知识' }, { name: '操作重型机械', base: 1, category: '操作' },
    { name: '说服', base: 10, category: '社交' }, { name: '驾驶', base: 20, category: '操作' },
    { name: '心理学', base: 10, category: '感知' }, { name: '精神分析', base: 1, category: '知识' },
    { name: '骑术', base: 5, category: '操作' }, { name: '科学', base: 1, category: '知识' },
    { name: '妙手', base: 10, category: '操作' }, { name: '潜行', base: 20, category: '操作' },
    { name: '侦查', base: 25, category: '感知' }, { name: '生存', base: 10, category: '操作' },
    { name: '游泳', base: 20, category: '操作' }, { name: '投掷', base: 20, category: '战斗' },
    { name: '追踪', base: 10, category: '感知' },
];

// ═══════════════════════════════════════════
//  Utility
// ═══════════════════════════════════════════

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

})();
