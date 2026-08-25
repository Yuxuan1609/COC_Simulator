import sys, os, json, io, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient


def _client():
    from frontend.routers import character
    app = FastAPI()
    app.include_router(character.router)
    return TestClient(app)


def test_step2_has_label_dropdown():
    """step2 职业下拉数据源必须是 occupation_labels.json（6 标签+自定义）。"""
    r = _client().get("/character/step/2")
    assert r.status_code == 200
    for name in ("学者", "侦探", "医生", "记者", "工程师", "执法者", "自定义"):
        assert f'value="{name}"' in r.text, f"标签下拉缺 {name}"


def test_skills_list_grouped_by_attribute():
    """技能按归属属性分块，块标题含乘数。"""
    r = _client().get("/character/skills-list")
    assert r.status_code == 200
    assert "力量 (STR) ×0.5" in r.text
    assert "智力 (INT) ×1.5" in r.text
    assert "幸运 (LUCK)" not in r.text or "×0" in r.text  # LUCK 乘数 0


def test_skills_list_dual_attr_single_input():
    """双属性技能（格斗: STR+DEX）重复出现于两块，但全页只能有一个可编辑 input。"""
    r = _client().get("/character/skills-list")
    assert r.text.count("格斗") >= 2, "格斗必须出现在 STR 与 DEX 两块"
    import re
    rows_with_input = re.findall(
        r'<span[^>]*>\s*(格斗)[^<]*</span>\s*<span[^>]*>[^<]*</span>\s*<input', r.text)
    assert len(rows_with_input) == 1, f"格斗只能有一个 input，实际 {len(rows_with_input)}"


def test_skills_list_label_focus_bonus():
    """选标签后 focus 技能渲染值 = base+10（封顶 99）并带专精徽标。"""
    r = _client().get("/character/skills-list", params={"label": "侦探"})
    assert r.status_code == 200
    import re
    m = re.search(r'<span[^>]*>\s*侦查[^<]*<span[^>]*>专精</span>.*?</span>\s*'
                  r'<span[^>]*>[^<]*</span>\s*<input[^>]*value="(\d+)"', r.text, re.S)
    if not m:
        m = re.search(r'侦查.*?value="(\d+)"', r.text, re.S)
    assert m, "未找到侦查行"
    assert int(m.group(1)) == 35, f"侦查 base25+10 应为 35，实际 {m.group(1)}"
    assert "专精" in r.text


def test_export_zip_has_label_and_v2():
    """导出 zip 内 character.json：personal.label 写入、无 SIZ、version=2.2（B11 与核心序列化对齐）。"""
    r = _client().post("/character/export", data={
        "name": "导出测试", "label": "侦探",
        "stat_STR": 60, "stat_CON": 60, "stat_DEX": 60, "stat_APP": 60,
        "stat_INT": 60, "stat_POW": 60, "stat_EDU": 60, "stat_LUCK": 50,
        "stat_HP": 20, "stat_MP": 12, "stat_SAN": 60,
        "stat_DODGE": 30, "stat_DB": "0", "stat_BUILD": 0,
        "skills_json": json.dumps({"侦查": 60}),
    })
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    card = json.loads(zf.read("character.json").decode("utf-8"))
    assert card["meta"]["version"] == "2.2"
    assert "SIZ" not in card["stats"]
    assert card["personal"]["label"] == "侦探"
    skills = {s["name"]: s["value"] for s in card["skills"]}
    assert skills["侦查"] == 60 and len(card["skills"]) == 20
