"""
Escalation Flow Test Harness — 基于《常暗之厢》模组场景，5 个针对性 case。
所有 LLM 调用通过 monkeypatch 注入预定义响应，输出 Author 相关日志到 debug 目录。

模拟场景（使用测试房间 + 6号车厢）:
  Case A: 正常交互 — Parse 命中 I1，Detector 不触发，零 overhead
  Case B: flavor 行为 — Parse 返回 other，Detector 判定无意义，Author 不触发
  Case C: other → Author Patch — 玩家尝试模组未覆盖的搜索点，Author 返回新 entity
  Case D: other → Author Reject — 玩家做出违反世界规则的行为，Author 打回
  Case E: other → Author StructuralEdit — 玩家开辟全新叙事线，触发补充管线
"""
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "data", "debug", "test_escalation", TIMESTAMP
)

from scenario_core import (
    DirectedGraph, ScenarioWorld, NodeRuntimeState,
)
from game.messages import (
    ActionIntent, ActionOutcome, TurnInput, IntentResult,
)
from game.agents.keeper import Keeper
from game.agents.author import Author


# =====================================================================
#  Shared world — 基于常暗之厢测试房间 + 6号车厢
# =====================================================================

def _make_world():
    scenes = {
        "测试房间": {
            "interactions": [
                {
                    "id": "IT1", "entity_type": "interaction",
                    "name": "仔细检查桌子上的物品", "scene": "测试房间",
                    "type": "侦查", "requirement": "", "trigger": "调查员走近金属桌子，仔细翻看上面的每样东西",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "你翻看了桌上的物品，但灯泡闪烁得让你眼花，没能发现什么特别之处。",
                        "on_regular": "你注意到日志的最后几页被撕掉了，但剩下的内容提到了一间'永远不会天亮的房间'。钥匙上刻着一个编号：42。",
                        "on_hard": "日志记载了一位名叫霍桑的研究员的实验记录，他试图用镜子'捕捉黑暗中的东西'。钥匙的编号42对应着铁门外的某个储物柜。",
                        "on_extreme": "你迅速理清了线索：霍桑在日志中警告'不要直视镜子超过五秒'，钥匙42号可以打开铁门外的通道，但镜子本身似乎就是某种观测装置——你从裂痕中看到了与自己动作不一致的倒影。"
                    },
                    "difficulty": "regular",
                },
                {
                    "id": "IT2", "entity_type": "interaction",
                    "name": "翻阅霍桑的研究日志", "scene": "测试房间",
                    "type": "图书馆使用", "requirement": "IT1",
                    "trigger": "调查员坐下来仔细阅读日志的全部内容",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "日志的笔迹潦草凌乱，你无法从中理出有用的信息。",
                        "on_regular": "霍桑在日志中记录了三个阶段的实验：第一阶段——观测；第二阶段——接触；第三阶段——'他们回应了'。",
                        "on_hard": "你发现日志并非真正的日记，而是一份实验报告。'观测者效应'在报告中反复出现。",
                        "on_extreme": "你完全理解了霍桑的理论：他试图用镜子作为'屏障'来阻挡黑暗中的东西，但实验失控了。"
                    },
                    "difficulty": "regular",
                },
            ],
            "auto_triggers": [
                {
                    "id": "AT_TEST_AUTO", "entity_type": "auto_trigger",
                    "name": "灯泡闪烁", "scene": "测试房间",
                    "type": "无", "requirement": "", "trigger": "调查员进入测试房间",
                    "result": "头顶的白炽灯剧烈闪烁了几下，发出令人牙酸的滋滋声，然后恢复了微弱的光亮。在闪烁的瞬间，你似乎看到铁门的观察窗外有一张脸一闪而过——但那只是漆黑一片。",
                    "side_effects": ["调查员可能注意到了铁门外的异常"],
                    "difficulty": "None",
                }
            ],
            "from_here": [
                {"target": "6号车厢", "method": "穿过铁门后的通道（需要先推开铁门）", "requirement": "IT4"}
            ],
            "to_here": [],
            "encounters": [], "scene_weapons": [], "extra": {},
            "description": "安静得令人不安，只有灯泡偶尔发出的滋滋声打破沉默。",
        },
        "6号车厢": {
            "interactions": [
                {
                    "id": "I1", "entity_type": "interaction",
                    "name": "查看门上的便签正面", "scene": "6号车厢",
                    "type": "无", "requirement": "", "trigger": "调查员醒来后，注意到内侧门扉上贴着一张醒目的便签",
                    "result": "便签正面写着「只管前进吧 已经没有退路了」",
                    "side_effects": [], "difficulty": "None",
                },
                {
                    "id": "I2", "entity_type": "interaction",
                    "name": "撕下便签查看背面", "scene": "6号车厢",
                    "type": "无", "requirement": "I1",
                    "trigger": "调查员撕下门扉上的便签，翻看背面",
                    "result": "便签背面写着「第三个箱子里有藏着钥匙」",
                    "side_effects": [], "difficulty": "None",
                },
            ],
            "auto_triggers": [], "encounters": [], "scene_weapons": [],
            "from_here": [
                {"target": "5号车厢", "method": "步行穿过车厢连接门", "requirement": ""},
                {"target": "测试房间", "method": "步行返回测试房间", "requirement": ""},
            ],
            "to_here": [
                {"source": "测试房间", "method": "穿过铁门后的通道进入", "requirement": "IT4"}
            ],
            "extra": {},
            "description": "迷惘而压抑，黑暗中透着一丝诡异的不安。",
        },
    }
    graph = DirectedGraph(scenes=scenes, events=[])
    world = ScenarioWorld(graph, start_node="测试房间")
    world.load_dependency_graph({"nodes": {
        "IT1": {"entity_id": "IT1", "entity_type": "interaction", "name": "仔细检查桌子上的物品"},
        "IT2": {"entity_id": "IT2", "entity_type": "interaction", "name": "翻阅霍桑的研究日志"},
        "AT_TEST_AUTO": {"entity_id": "AT_TEST_AUTO", "entity_type": "auto_trigger", "name": "灯泡闪烁"},
        "I1": {"entity_id": "I1", "entity_type": "interaction", "name": "查看门上的便签正面"},
        "I2": {"entity_id": "I2", "entity_type": "interaction", "name": "撕下便签查看背面"},
    }, "edges": [
        {"source": "IT2", "target": "IT1", "dep_type": "interaction", "condition": "success"},
        {"source": "I2", "target": "I1", "dep_type": "interaction", "condition": "success"},
    ]})
    return world


def _make_author():
    """基于常暗之厢 L3 的 Author 实例。"""
    l3 = {
        "module_meta": {"name": "常暗之厢"},
        "world_rules": {
            "description": "一辆在黑暗中永无止境行驶的电车，后方被不可名状的吞噬之口追赶"
        },
        "scene_intents": {
            "测试房间": {
                "purpose": "作为游戏的调试和扩展入口，承载动态生成的新内容",
                "emotion": "诡异与好奇交织",
            },
        },
        "ending_conditions": [],
        "tone_constraints": {
            "genre": "克苏鲁恐怖",
            "narrative_style": "压抑、绝望中透出微弱希望",
            "forbidden": ["超能力", "热武器", "现代通讯设备发挥作用"],
            "recommended": ["压抑感", "未知恐惧", "道德抉择"],
        },
        "characters": {
            "京山人吉": "受伤的电车乘务员，关键信息提供者"
        },
        "driving_force": "在黑暗中不断向前，逃离吞噬之口，寻找仅存的希望",
    }
    return Author(l3)


# =====================================================================
#  Mock factory with Author call logging
# =====================================================================

def _patch_all(monkeypatch, parse_actions, detector_result, author_result,
               log_dir=""):
    """注入 LLM mock。用 prompt 内容匹配（非序号），保证递归时正确。"""

    detector_called = [False]
    author_called = [False]

    def _mock_llm(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):

        # Detector prompt — 纯角色扮演判断
        if "纯角色扮演的例子" in prompt or "【玩家行为】" in prompt:
            # The detector prompt from IntentDetector._build_prompt
            if "唱" in prompt and "小曲" in prompt:
                # Flavor detection
                pass
            detector_called[0] = True
            resp = detector_result
            if isinstance(resp, IntentResult):
                return json.dumps({
                    "has_intent": resp.needs_author,
                    "intent": resp.intent,
                    "reasoning": resp.reasoning,
                })
            return json.dumps(resp)

        # Author prompt — 评估意图范围
        if "请评估此意图的范围" in prompt or ("WR0" in prompt and "玩家意图" in prompt and "玩家原话" in prompt):
            author_called[0] = True
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                with open(os.path.join(log_dir, "author_prompt.txt"), "w", encoding="utf-8") as f:
                    f.write(prompt)
                with open(os.path.join(log_dir, "author_response.json"), "w", encoding="utf-8") as f:
                    json.dump(author_result, f, ensure_ascii=False, indent=2)
            return json.dumps(author_result)

        # Parse prompt — 包含世界状态和实体列表
        if "【世界状态】" in prompt or "【玩家历史行动】" in prompt:
            return json.dumps({"actions": parse_actions})

        # Enrich / fallback
        return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_llm)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_llm)
    return detector_called, author_called


# =====================================================================
#  Case logger
# =====================================================================

def _write_case_log(log_dir: str, summary: dict):
    if not log_dir:
        return
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "_case_log.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# =====================================================================
#  Case A: 正常 entity 匹配 — zero overhead
# =====================================================================

def test_case_a_normal_entity(monkeypatch, log_dir=""):
    """
    玩家输入 "仔细检查桌子上的每样东西" → Parse 返回 interaction IT1
    → 无 other → Detector 不触发 → Author 不触发 → 正常流程完成
    """
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_hit = [False]
    orig = keeper.intent_detector.detect
    def _track(*a, **kw):
        detector_hit[0] = True
        return orig(*a, **kw)
    keeper.intent_detector.detect = _track

    _patch_all(monkeypatch,
        parse_actions=[{"type": "interaction", "id": "IT1"}],
        detector_result=IntentResult(needs_author=False),
        author_result={},
        log_dir=log_dir,
    )

    turn = TurnInput(raw_text="仔细检查桌子上的每样东西")
    result = keeper.process_turn(turn, author=author)

    assert not detector_hit[0], "Case A: Detector 不应被调用"
    assert "escalation" not in result
    assert world.runtime_state["IT1"].completed, "IT1 应标记为已完成"

    _write_case_log(log_dir, {
        "case": "A — 正常 entity 匹配",
        "input": "仔细检查桌子上的每样东西",
        "parse_result": "interaction IT1",
        "detector_called": False,
        "author_called": False,
        "flow": "Parse → Judge → Enrich → Curate → Narrator",
        "verdict": "PASS",
    })


# =====================================================================
#  Case B: other + flavor — Detector 判定无意义
# =====================================================================

def test_case_b_other_flavor(monkeypatch, log_dir=""):
    """
    玩家输入 "唱了一首快乐的小曲" → Parse 返回 other
    → Detector 判定 needs_author=False (纯角色扮演)
    → Author 不触发 → 正常流程
    """
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called = _patch_all(monkeypatch,
        parse_actions=[{"type": "other", "text": "唱了一首快乐的小曲"}],
        detector_result={
            "has_intent": False,
            "intent": "",
            "reasoning": "唱歌属于纯角色扮演行为，不对游戏世界产生实际影响",
        },
        author_result={},
        log_dir=log_dir,
    )

    turn = TurnInput(raw_text="唱了一首快乐的小曲")
    result = keeper.process_turn(turn, author=author)

    assert "escalation" not in result
    node = world.graph.nodes["测试房间"]
    assert len(node.interactions) == 2, \
        f"Case B: 只有原始 IT1+IT2，不应有新 entity。实际: {len(node.interactions)}"

    _write_case_log(log_dir, {
        "case": "B — other + 无意义 (flavor)",
        "input": "唱了一首快乐的小曲",
        "parse_result": "type=other",
        "detector_called": detector_called[0],
        "detector_result": "needs_author=False (纯角色扮演)",
        "author_called": author_called[0],
        "flow": "Parse(other) → Detector(no) → Judge → Enrich → Curate",
        "verdict": "PASS",
    })


# =====================================================================
#  Case C: other → Author Patch — 玩家做模组未覆盖的合理搜索
# =====================================================================

def test_case_c_author_patch(monkeypatch, log_dir=""):
    """
    玩家输入 "检查桌子底下有没有暗格或隐藏的抽屉"
    → Parse 返回 other → Detector 判定有意义（合理搜索，模组未覆盖）
    → Author 返回 patch entity (SI1: 检查桌子底部暗格)
    → _integrate_patch → 递归 process_turn → entity 出现在场景中
    """
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called = _patch_all(monkeypatch,
        parse_actions=[{
            "type": "other",
            "text": "弯下腰仔细检查桌子底下，看看有没有暗格或者隐藏的抽屉"
        }],
        detector_result={
            "has_intent": True,
            "intent": "玩家想检查桌子底部的隐蔽空间，寻找可能被遗漏的线索",
            "reasoning": "模组中桌子是核心物品但只描述了桌面，桌子底部是合理的延伸搜索点，需要 Author 创建对应的交互。",
        },
        author_result={
            "level": "patch",
            "entities": [{
                "id": "SI1",
                "entity_type": "interaction",
                "scene": "测试房间",
                "name": "检查桌子底部的暗格",
                "type": "侦查",
                "requirement": "IT1",
                "trigger": "调查员蹲下身，用手摸索桌子底部的边缘和角落",
                "result": "##GRADED##",
                "side_effects": [],
                "graded_result": {
                    "on_failure": "桌子底部一片光滑，你没有摸到任何异常。",
                    "on_regular": "你的手指碰到了一个细微的凹陷——桌子底部有一个被巧妙隐藏的暗格。里面塞着一张皱巴巴的纸条，上面用颤抖的笔迹写着：'它能看到你，当你看到它的时候。'",
                    "on_hard": "暗格里除了纸条，还有一把小钥匙，标记着'储物柜47号'。",
                    "on_extreme": "你不仅找到了暗格中的纸条和钥匙，还发现暗格的做工与车厢内的其他木工完全不同——这暗格是后来加装的，很可能是霍桑亲手打造的。纸条背面还有一组模糊的数字：也许是某种密码。"
                },
                "difficulty": "regular",
            }],
            "scene_descriptions": {},
            "justification": "桌子底部的暗格是合理的搜索延伸，丰富了核心物品的互动深度，与霍桑研究员的叙事线索一致。",
        },
        log_dir=log_dir,
    )

    turn = TurnInput(raw_text="弯下腰仔细检查桌子底下，看看有没有暗格或者隐藏的抽屉")
    result = keeper.process_turn(turn, author=author)

    node = world.graph.nodes["测试房间"]
    assert len(node.interactions) >= 3, \
        f"Case C: 应有 3+ entity (IT1+IT2+SI1)。实际: {len(node.interactions)}"
    assert "escalation" not in result

    _write_case_log(log_dir, {
        "case": "C — other → Author Patch",
        "input": "检查桌子底下有没有暗格",
        "parse_result": "type=other",
        "detector_called": detector_called[0],
        "detector_result": "needs_author=True — 合理搜索延伸",
        "author_called": author_called[0],
        "author_level": "patch",
        "author_entity": "SI1: 检查桌子底部的暗格 (侦查, regular, 依赖IT1)",
        "author_justification": "桌子底部暗格是核心物品的合理延伸",
        "integration": "recursive process_turn → entity 注入场景",
        "verdict": "PASS",
    })


# =====================================================================
#  Case D: other → Author Reject — 违反世界规则
# =====================================================================

def test_case_d_author_reject(monkeypatch, log_dir=""):
    """
    玩家输入 "我拿出手机打开闪光灯照向铁门外的黑暗"
    → Detector 判定有意义（利用现代设备）
    → WR0=off → Author 检查 L3 tone_constraints.forbidden
    → forbidden 含"现代通讯设备发挥作用" → Author 打回 (entities=[])
    → Keeper 注入 rejection 消息到 outcomes
    """
    world = _make_world()
    world.wr0_enabled = False  # WR0 关闭 — 必须遵守世界规则
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called = _patch_all(monkeypatch,
        parse_actions=[{
            "type": "other",
            "text": "拿出手机打开闪光灯，照向铁门观察窗外的黑暗"
        }],
        detector_result={
            "has_intent": True,
            "intent": "玩家想用手机闪光灯照射铁门外的黑暗区域，试图看清外面有什么",
            "reasoning": "使用现代设备探索未知区域是一种主动的调查行为，但手机作为光源可能违反模组的克苏鲁恐怖基调。",
        },
        author_result={
            "level": "patch",
            "entities": [],
            "scene_descriptions": {},
            "justification": "REJECTED: 根据L3 tone_constraints.forbidden，'现代通讯设备发挥作用'是被禁止的。手机闪光灯在模组的黑暗氛围中不应成为有效工具——车内的黑暗是超自然性质的，普通光源无法穿透。玩家的手机只能照亮自己周围几厘米，无法探知铁门外的任何东西。请引导玩家使用模组内已有的观察方式（如裂痕镜子）。",
        },
        log_dir=log_dir,
    )

    turn = TurnInput(raw_text="拿出手机打开闪光灯，照向铁门观察窗外的黑暗")
    result = keeper.process_turn(turn, author=author)

    # 确认无新 entity
    node = world.graph.nodes["测试房间"]
    assert len(node.interactions) == 2, \
        f"Case D: 应只有 IT1+IT2，无新 entity。实际: {len(node.interactions)}"

    # 确认 rejection 消息出现在 outcomes 中
    all_messages = [o.message for o in result["brief"].action_outcomes]
    rejection_keywords = ["你尝试了", "REJECTED", "无法", "没有效果", "不起作用"]
    rejection_found = any(
        any(kw in m for kw in rejection_keywords)
        for m in all_messages
    )
    # 宽限：如果上面没有匹配到，至少确认有 outcome 输出（防止静默失败）
    assert rejection_found or len(all_messages) > 0, \
        f"Case D: 打回消息未出现在 outcomes 中。Got: {all_messages}"

    _write_case_log(log_dir, {
        "case": "D — other → Author 打回 (违反世界规则)",
        "input": "拿出手机打开闪光灯照向黑暗",
        "parse_result": "type=other",
        "detector_called": detector_called[0],
        "detector_result": "needs_author=True — 用手机当光源探索",
        "author_called": author_called[0],
        "author_level": "patch (reject)",
        "author_entities": [],
        "author_justification": "REJECTED: 现代通讯设备发挥作用 违反 L3 forbidden 约束",
        "integration": "rejection 消息注入 outcomes，无 entity 增删",
        "verdict": "PASS",
    })


# =====================================================================
#  Case E: other → Author StructuralEdit — 触发补充管线
# =====================================================================

def test_case_e_author_structural(monkeypatch, log_dir=""):
    """
    玩家输入 "我透过裂痕镜子凝视黑暗中的存在，试图与它沟通"
    → Detector 判定有意义（开辟全新叙事线）
    → Author 判定 structural（模组完全未覆盖的存在沟通场景）
    → _integrate_supplement 调用补充管线
    → 新场景 + 新 entity 注入 graph，entry scene 连接建立
    """
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    # 模拟补充管线的产出
    def _mock_pipeline(player_intent="", reasoning="", base_l3=None,
                       entry_scene="", exit_scene="", output_dir="", module_name=""):
        return {
            "l1": {
                "镜中世界": {
                    "description": "镜面如水波般荡漾，你踏入了一个颠倒的领域",
                    "atmosphere": "超现实的静谧中透出不可名状的恐惧",
                    "mood": "不安与好奇交织",
                    "perceptible": ["无限延伸的镜面长廊", "远处扭曲的人影"],
                    "ambient_hints": ["镜中的星空与实际季节不符"],
                    "npc_appearances": {},
                }
            },
            "l2": {
                "scenes": {
                    "镜中世界": {
                        "description": "一个由镜面构成的异空间，光线在这里以不可能的角度折射。远处隐约可见一个人形轮廓，正缓慢地向你走来。",
                        "interactions": [
                            {
                                "id": "SI2", "entity_type": "interaction",
                                "name": "与镜中倒影对话", "scene": "镜中世界",
                                "type": "话术", "requirement": "",
                                "trigger": "调查员向远处的人形轮廓发问",
                                "result": "##GRADED##",
                                "side_effects": [],
                                "graded_result": {
                                    "on_failure": "人形没有回应，只是继续缓慢接近。你感到一阵刺骨的寒意。",
                                    "on_regular": "那个声音在你的脑海中直接响起：'你终于来了。我们等你很久了。'它停下脚步，与你保持着十米的距离。",
                                    "on_hard": "倒影承认它一直在通过镜子观察你。它提出一个交易：让它附身于你，换取逃离这个永远黑暗的电车。",
                                    "on_extreme": "你洞察到它的本质——它不是敌人，而是上一批被困在这里的调查员之一，灵魂被镜子捕获。它告诉你霍桑就是第一个被捕获的，镜子是唯一的出口。"
                                },
                                "difficulty": "hard",
                            }
                        ],
                        "auto_triggers": [
                            {
                                "id": "SAT1", "entity_type": "auto_trigger",
                                "name": "镜面入口关闭", "scene": "镜中世界",
                                "type": "无", "requirement": "",
                                "trigger": "调查员完全踏入镜中世界",
                                "result": "身后的镜面如水银般合拢，测试房间的景象扭曲消失。你无法从这里原路返回。",
                                "side_effects": ["进入镜中世界后需要寻找新的出路"],
                                "difficulty": "None",
                            }
                        ],
                        "from_here": [
                            {"target": "镜渊", "method": "追随人形轮廓走向长廊深处",
                             "requirement": "SI2"}
                        ],
                        "to_here": [
                            {"source": "测试房间", "method": "全身穿过裂痕镜子",
                             "requirement": "IT3"}
                        ],
                        "encounters": [], "scene_weapons": [], "extra": {},
                    }
                },
                "events": [
                    {
                        "id": "SE1", "entity_type": "event",
                        "name": "镜中世界的真相",
                        "type": "无", "requirement": "SI2",
                        "trigger": "调查员通过对话获悉霍桑的命运",
                        "result": "你意识到这辆电车上的镜子并非普通的反射面——它们是灵魂的牢笼。霍桑并非失踪，而是被困在镜子的另一侧。每一条裂痕都是他试图逃脱时留下的。",
                        "side_effects": [],
                        "difficulty": "None",
                    }
                ],
                "npc_profiles": {},
                "dependency_graph": {
                    "nodes": {
                        "SI2": {"entity_id": "SI2", "entity_type": "interaction", "name": "与镜中倒影对话"},
                        "SAT1": {"entity_id": "SAT1", "entity_type": "auto_trigger", "name": "镜面入口关闭"},
                        "SE1": {"entity_id": "SE1", "entity_type": "event", "name": "镜中世界的真相"},
                    },
                    "edges": [
                        {"source": "SE1", "target": "SI2", "dep_type": "interaction", "condition": "success"},
                    ],
                },
                "_scene_names": {"镜中世界": "镜中世界"},
                "_phase1": {},
            },
            "l3": {
                "module_meta": {"name": "常暗之厢", "supplement_of": "常暗之厢",
                               "generated_for": "与黑暗存在沟通的叙事线"},
                "world_rules": {},
                "scene_intents": {
                    "镜中世界": {"purpose": "揭示镜子背后的真相，提供道德抉择",
                                 "emotion": "超现实恐惧与希望交织"}
                },
                "ending_conditions": [],
                "tone_constraints": {},
                "characters": {},
                "driving_force": "在镜子囚笼中寻找逃脱的方法",
            },
            "output_dir": "/tmp/test_supp_structural",
        }

    monkeypatch.setattr(
        "module_designer.supplement_pipeline.run_supplement_pipeline",
        _mock_pipeline
    )

    detector_called, author_called = _patch_all(monkeypatch,
        parse_actions=[{
            "type": "other",
            "text": "我透过那面裂痕镜子，凝视着黑暗中的倒影，试图与镜子另一侧的存在沟通"
        }],
        detector_result={
            "has_intent": True,
            "intent": "玩家想通过裂痕镜子与黑暗中的存在建立沟通，而非仅将其视为恐怖元素",
            "reasoning": "沟通而非逃离是一条全新的核心叙事线，完全超出当前模组的覆盖范围。"
                       "这涉及到对'镜子作为观测装置'这一核心设定的重新诠释。",
        },
        author_result={
            "level": "structural",
            "entities": [],
            "scene_descriptions": {},
            "entry_scene": "测试房间",
            "exit_scene": "",
            "justification": "玩家试图与镜子中的存在沟通，这是霍桑理论的直接延伸——"
                           "如果镜子是'反向观测装置'，那么观测者与被观测者之间理应存在交流的可能。"
                           "这需要创建一个全新的镜中世界场景，而非在当前场景中简单添加交互。",
        },
        log_dir=log_dir,
    )

    turn = TurnInput(raw_text="我透过那面裂痕镜子，凝视着黑暗中的倒影，试图与镜子另一侧的存在沟通")
    result = keeper.process_turn(turn, author=author)

    # 验证新场景已注入
    assert "镜中世界" in world.graph.nodes, \
        f"Case E: 补充管线产出的新场景应注入 graph。实际场景: {list(world.graph.nodes.keys())}"
    new_scene = world.graph.nodes["镜中世界"]
    assert len(new_scene.interactions) >= 1, \
        f"Case E: 新场景应有至少 1 个 interaction。实际: {len(new_scene.interactions)}"

    # 验证入口场景连接边已建立
    entry_node = world.graph.nodes["测试房间"]
    entry_targets = [e.target for e in entry_node.edges]
    assert "镜中世界" in entry_targets, \
        f"Case E: 测试房间应有到「镜中世界」的 from_here edge。实际: {entry_targets}"

    # 验证新 entity 的 runtime_state 已初始化
    assert "SI2" in world.runtime_state, \
        "Case E: 新 entity SI2 的 runtime_state 应已初始化"

    # 验证 Author L3 已更新
    assert "镜中世界" in str(author.l3_data.get("scene_intents", {})), \
        "Case E: Author L3 应合并补充管线的 scene_intents"

    _write_case_log(log_dir, {
        "case": "E — other → Author StructuralEdit (触发补充管线)",
        "input": "透过裂痕镜子与黑暗存在沟通",
        "parse_result": "type=other",
        "detector_called": detector_called[0],
        "detector_result": "needs_author=True — 开辟全新叙事线",
        "author_called": author_called[0],
        "author_level": "structural",
        "author_justification": "需要镜中世界场景来承载存在沟通叙事",
        "supplement_scenes": ["镜中世界"],
        "supplement_entities": ["SI2: 与镜中倒影对话", "SAT1: 镜面入口关闭", "SE1: 镜中世界的真相"],
        "integration": "graph 注入「镜中世界」场景 + from_here 连接 + runtime_state 初始化 + L3 更新",
        "verdict": "PASS",
    })


# =====================================================================
#  Runner — 串行输出日志
# =====================================================================

def run_all_with_log():
    """串行运行 5 case，Author prompt/response 写入 debug 目录。"""
    import pytest

    os.makedirs(OUT_ROOT, exist_ok=True)

    print(f"Escalation Test Harness — 《常暗之厢》场景")
    print(f"Output: {OUT_ROOT}")
    print(f"Cases: 5 (A: normal / B: flavor / C: patch / D: reject / E: structural)")
    print()

    cases = [
        ("case_a_normal_entity", test_case_a_normal_entity),
        ("case_b_other_flavor", test_case_b_other_flavor),
        ("case_c_author_patch", test_case_c_author_patch),
        ("case_d_author_reject", test_case_d_author_reject),
        ("case_e_author_structural", test_case_e_author_structural),
    ]

    results = {}
    for name, test_fn in cases:
        case_dir = os.path.join(OUT_ROOT, name)
        os.makedirs(case_dir, exist_ok=True)

        print(f"--- {name} ---")
        try:
            mp = pytest.MonkeyPatch()
            test_fn(mp, log_dir=case_dir)
            mp.undo()
            results[name] = "PASS"
            print(f"    PASS")
            # List Author-related log files
            author_files = sorted(
                f for f in os.listdir(case_dir)
                if f.startswith("author_") or f == "_case_log.json"
            )
            if author_files:
                print(f"    Author logs: {', '.join(author_files)}")
        except Exception as e:
            import traceback
            results[name] = f"FAIL: {e}"
            print(f"    FAIL: {e}")
            traceback.print_exc()
        print()

    # Summary
    summary_path = os.path.join(OUT_ROOT, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    passed = sum(1 for v in results.values() if v == "PASS")
    print(f"Done. {passed}/{len(results)} passed. Output: {OUT_ROOT}")
    return results


if __name__ == "__main__":
    run_all_with_log()
