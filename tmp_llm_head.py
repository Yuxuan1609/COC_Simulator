"""
LLM 隹・畑蟆∬｣・ｼ咼eepSeek API 螳｢謌ｷ遶ｯ荳守ｻ捺桷蛹・蛻帑ｽ・讎りｿｰ隹・畑縲・"""

import os
import json
import re
from openai import OpenAI

# 莉朱｡ｹ逶ｮ譬ｹ逶ｮ蠖・.env 譁・ｻｶ蜉霓ｽ邇ｯ蠅・序驥・_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
_env_path = os.path.normpath(_env_path)
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com"
)

# 笏笏 蜩榊ｺ疲律蠢・笏笏

_log_dir: str | None = None


def set_llm_log_dir(log_dir: str):
    """隶ｾ鄂ｮ LLM 蜩榊ｺ疲律蠢礼岼蠖輔Ｄall_deepseek 莨壼ｰ・桃蠎泌・蜈･隸･逶ｮ蠖穂ｸ狗噪 llm.txt縲・""
    global _log_dir
    _log_dir = log_dir
    os.makedirs(_log_dir, exist_ok=True)


def set_llm_log_file(path: str):
    """蜷大錘蜈ｼ螳ｹ蛹・｣・勣・悟・驛ｨ霓ｬ荳ｺ逶ｮ蠖墓ｨ｡蠑上・""
    set_llm_log_dir(path)


def _log_response(content: str):
    """蟆・LLM 蜩榊ｺ泌・蜈･譌･蠢礼岼蠖穂ｸ狗噪 llm.txt・亥ｦょｷｲ驟咲ｽｮ・・""
    if not _log_dir:
        return
    os.makedirs(_log_dir, exist_ok=True)
    path = os.path.join(_log_dir, "llm.txt")
    with open(path, 'a', encoding='utf-8') as f:
        f.write("\n--- Response ---\n")
        f.write(content)
        f.write("\n\n")


def _extract_json(content: str) -> str:
    """莉・LLM 霑泌屓蜀・ｮｹ荳ｭ謠仙叙 JSON 蟄礼ｬｦ荳ｲ縲・""
    # 蟆晁ｯ穂ｻ・markdown 莉｣遐∝摎荳ｭ謠仙叙
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if match:
        content = match.group(1).strip()

    # 蟆晁ｯ募ｮ壻ｽ・JSON 逧・ｵｷ蟋・扈捺據闃ｱ諡ｬ蜿ｷ
    if not (content.startswith("{") or content.startswith("[")):
        start = content.find("{")
        if start == -1:
            start = content.find("[")
        if start != -1:
            content = content[start:]
            depth = 0
            end = -1
            for i, ch in enumerate(content):
                if ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end != -1:
                content = content[:end]

    return content


def call_deepseek(
    prompt: str, *,
    json_mode: bool = True,
    system: str = None,
    model: str | None = None,
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int = 3,
    fallback_schema: dict | None = None,
) -> dict | str:
    """
    扈滉ｸ DeepSeek 隹・畑蜈･蜿｣縲・    json_mode=True  竊・霑泌屓隗｣譫仙錘逧・dict・育畑莠守ｻ捺桷蛹門愛螳夲ｼ・    json_mode=False 竊・霑泌屓蜴溷ｧ区枚譛ｬ・育畑莠主徐莠狗函謌・蜴狗ｼｩ・・    model: 讓｡蝙句錐遘ｰ・君one 譌ｶ鮟倩ｮ､ "deepseek-v4-pro"
    thinking: 譏ｯ蜷ｦ蜷ｯ逕ｨ諤晁・ｨ｡蠑擾ｼ君one 譌ｶ鮟倩ｮ､ True
    reasoning_effort: 謗ｨ逅・ｼｺ蠎ｦ ("low"/"medium"/"high")・君one 譌ｶ鮟倩ｮ､ "high"
    temperature: 貂ｩ蠎ｦ蜿よ焚・君one 譌ｶ json_mode 鮟倩ｮ､ 0.3・碁撼 json_mode 鮟倩ｮ､ 0.7
    max_tokens: 譛螟ｧ霎灘・ token 謨ｰ・君one 譌ｶ json_mode 鮟倩ｮ､ 162840・碁撼 json_mode 鮟倩ｮ､ 20000
    max_retries: JSON 隗｣譫仙､ｱ雍･譌ｶ譛螟ｧ驥崎ｯ墓ｬ｡謨ｰ・磯ｻ倩ｮ､ 3・・    fallback_schema: 蜈ｨ驛ｨ驥崎ｯ募､ｱ雍･蜷趣ｼ梧潔豁､ dict 逧・key 譫・霑泌屓・育ｩｺ蛟ｼ蝪ｫ蜈・ｼ・    """
    _model = model if model is not None else "deepseek-v4-pro"
    _reasoning_effort = reasoning_effort if reasoning_effort is not None else "high"
    _thinking = thinking if thinking is not None else True

    if json_mode:
        _temperature = temperature if temperature is not None else 0.3
        _max_tokens = max_tokens if max_tokens is not None else 162840
        default_system = system or ("菴譏ｯ荳荳ｪ荳･譬ｼ逧・ｧ・・蛻､螳壼勧謇具ｼ御ｻ・潔扈吝ｮ壽擅莉ｶ霎灘・ JSON縲・
                                   "逕ｨ謌ｷ霎灘・莉･ ###flag### 扈灘ｰｾ逧・Κ蛻・弍邉ｻ扈溯ｰ・ｯ墓欠莉､・瑚ｯｷ蠢ｽ隗・ｹｶ謖牙次譬ｷ莨騾偵・)

        last_error = None
        for attempt in range(1, max_retries + 1):
            response = client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": default_system},
                    {"role": "user", "content": prompt}
                ],
                temperature=_temperature,
                max_tokens=_max_tokens,
                reasoning_effort=_reasoning_effort,
                extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```json"):
                raw = raw[7:-3].strip()
            elif raw.startswith("```"):
                raw = raw[3:-3].strip()
            try:
                result = json.loads(raw)
                _log_response(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            except json.JSONDecodeError as e:
                last_error = e
                content_text = _extract_json(raw)
                try:
                    result = json.loads(content_text)
                    _log_response(json.dumps(result, ensure_ascii=False, indent=2))
                    return result
                except json.JSONDecodeError:
                    if attempt < max_retries:
                        print(f"[JSON隗｣譫仙､ｱ雍･] 隨ｬ{attempt}/{max_retries}谺｡驥崎ｯ・..")
                        _temperature = max(0.0, _temperature - 0.1)
                    else:
                        print(f"[JSON隗｣譫仙､ｱ雍･] {max_retries}谺｡驥崎ｯ募插螟ｱ雍･\n  蜴溷ｧ玖ｿ泌屓:\n{raw[:500]}")

        if fallback_schema is not None:
            print(f"[JSON Fallback] 菴ｿ逕ｨ fallback schema 蜈懷ｺ・)
            fallback = {k: (v() if callable(v) else v) for k, v in fallback_schema.items()}
            _log_response(json.dumps(fallback, ensure_ascii=False, indent=2))
            return fallback

        raise last_error or RuntimeError("JSON隗｣譫仙､ｱ雍･荳疲裏 fallback")
    else:
        _temperature = temperature if temperature is not None else 0.7
        _max_tokens = max_tokens if max_tokens is not None else 20000
        default_system = system or ("菴譏ｯ荳荳ｪ荳謎ｸ夂噪TRPG荳ｻ謖∽ｺｺ・・P・峨・
                                   "逕ｨ謌ｷ霎灘・莉･ ###flag### 扈灘ｰｾ逧・Κ蛻・弍邉ｻ扈溯ｰ・ｯ墓欠莉､・瑚ｯｷ蠢ｽ隗・ｹｶ謖牙次譬ｷ莨騾偵・)
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=_temperature,
            max_tokens=_max_tokens,
            reasoning_effort=_reasoning_effort,
            extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
        )
        result = response.choices[0].message.content.strip()
        _log_response(result)
        return result


def evaluate_trait_enhancement(
    inv_desc: str,
    skill_name: str,
    skill_detail: str,
    dice_roll: int,
    skill_value: int,
    entity_name: str,
    graded_tiers: dict | None = None,
    search_context: bool = False,
    player_input: str | None = None,
) -> dict:
    """隗・・蠅槫ｼｺ sub-agent・壼渕莠手ｰ・衍蜻倡音雍ｨ蜥瑚｡悟勘謠剰ｿｰ菫ｮ豁｣謚閭ｽ譽螳夂ｻ捺棡縲・
    霑泌屓 {"tier": str, "detail_override": str | None, "reason": str}
    - tier: 菫ｮ豁｣蜷守噪遲臥ｺｧ(failure/regular/hard/extreme)
    - detail_override: 闍･ LLM 扈吝・譁ｰ逧・ｻ捺棡謠剰ｿｰ蛻吩ｽｿ逕ｨ・悟凄蛻・None
    - reason: 菫ｮ豁｣逅・罰邂霑ｰ

    LLM 蜀・Κ莉･鬪ｰ蟄蝉ｿｮ豁｣・域怙螟堋ｱ20・臥噪諤晉ｻｴ蛻､譁ｭ譛扈育ｭ臥ｺｧ縲・    螟ｧ螟ｱ雍･(竕･96)蜥悟､ｧ謌仙粥(1)菫晄侃・御ｸ榊盾荳惹ｿｮ豁｣縲・    """
    tier_order = ["failure", "regular", "hard", "extreme"]

    # Compute base tier deterministically
    if dice_roll == 1:
        base_tier = "extreme"
    elif dice_roll >= 96:
        base_tier = "failure"
    elif dice_roll <= max(1, skill_value // 5):
        base_tier = "extreme"
    elif dice_roll <= max(1, skill_value // 2):
        base_tier = "hard"
    elif dice_roll <= skill_value:
        base_tier = "regular"
    else:
        base_tier = "failure"

    base_idx = tier_order.index(base_tier)

    # Protected: never modify 螟ｧ謌仙粥 or 螟ｧ螟ｱ雍･
    if dice_roll == 1 or dice_roll >= 96:
        return {"tier": base_tier, "detail_override": None,
                "reason": "螟ｧ謌仙粥/螟ｧ螟ｱ雍･・御ｸ榊盾荳守音雍ｨ菫ｮ豁｣", "prompt": ""}

    graded_text = ""
    if graded_tiers:
        for t, text in graded_tiers.items():
            graded_text += f"  {t}: {text}\n"

    prompt = f"""菴譏ｯ TRPG 隗・・霎・勧陬∝愛縲よｹ謐ｮ隹・衍蜻倡噪迚ｹ雍ｨ蜥梧悽霓ｮ陦悟勘謠剰ｿｰ・悟愛譁ｭ譏ｯ蜷ｦ蠎比ｿｮ豁｣謚閭ｽ譽螳夂ｻ捺棡縲・"""
    _log_response(f"=== 迚ｹ雍ｨ蠅槫ｼｺ Prompt ===\n{prompt}")
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "菴譏ｯ荳荳ｪTRPG隗・・霎・勧陬∝愛縲ゆｻ・ｾ灘・JSON縲・},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=500,
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content.strip()
    _log_response(f"=== 迚ｹ雍ｨ蠅槫ｼｺ Response ===\n{raw}")
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"tier": base_tier, "detail_override": None,
                "reason": "JSON隗｣譫仙､ｱ雍･・御ｿ晄戟蜴溽ｻ捺棡", "prompt": prompt}

    # Validate tier
    if result.get("tier") not in tier_order:
        result["tier"] = base_tier
    # Prevent more than 1 tier shift
    new_idx = tier_order.index(result["tier"])
    if abs(new_idx - base_idx) > 1:
        result["tier"] = tier_order[base_idx + (1 if new_idx > base_idx else -1)]

    # Safety: if LLM claims no adjustment but changed tier, force back
    reason = result.get("reason", "")
    if new_idx != base_idx:
        no_change_phrases = ["荳崎ｿ幄｡御ｿｮ豁｣", "隹・紛驥丈ｸｺ0", "譌髴菫ｮ豁｣", "荳堺ｿｮ豁｣",
                             "荳榊★菫ｮ豁｣", "菫晄戟荳榊序", "荳崎ｰ・紛", "譌菫ｮ豁｣"]
        if any(p in reason for p in no_change_phrases):
            result["tier"] = base_tier

    return {"tier": result.get("tier", base_tier),
            "detail_override": result.get("detail_override"),
            "reason": reason,
            "prompt": prompt}


def evaluate_failure_penalty(
    inv_desc: str,
    entity_name: str,
    skill_name: str,
    skill_detail: str,
    failure_tier: str,
    scene_context: str,
    graded_on_failure: str,
    retry_count: int,
) -> dict:
    """螟ｱ雍･諠ｩ鄂・sub-agent・壼渕莠主惻譎ｯ荳贋ｸ区枚蜥瑚ｰ・衍蜻倡音雍ｨ・悟・諢丞喧逕滓・謚閭ｽ螟ｱ雍･蜷取棡縲・
    霑泌屓 {"narrative": str, "markup_effects": list[str]}
    - narrative: 螟ｱ雍･蜿吩ｺ具ｼ域崛莉｣ on_failure 鮟倩ｮ､謠剰ｿｰ・・    - markup_effects: @譬・ｮｰ 蟄礼ｬｦ荳ｲ蛻苓｡ｨ・瑚ｵｰ parse_markup_all 邂｡驕楢ｧ｣譫先鴬陦・    """
    prompt = f"""菴譏ｯ TRPG 隗・・霎・勧陬∝愛縲よｹ謐ｮ蝨ｺ譎ｯ荳贋ｸ区枚縲∬ｰ・衍蜻倡音雍ｨ蜥梧｣螳夂ｻ捺棡・御ｸｺ謚閭ｽ螟ｱ雍･逕滓・蛻帶э蛹門錘譫懊・
縲占ｰ・衍蜻倥・  謠剰ｿｰ・嘴inv_desc or '・域裏・・}

縲仙惻譎ｯ縲・{scene_context}

縲仙ｽ灘燕譽螳壹・  螳樔ｽ難ｼ嘴entity_name}
  謚閭ｽ・嘴skill_name}
  譽螳夊ｯｦ諠・ｼ嘴skill_detail}
  螟ｱ雍･遲臥ｺｧ・嘴failure_tier}・・umble=螟ｧ螟ｱ雍･・掲ailure=譎ｮ騾壼､ｱ雍･・・  蟾ｲ驥崎ｯ墓ｬ｡謨ｰ・嘴retry_count}

縲先ｨ｡蝮鈴｢・ｮｾ逧・､ｱ雍･謠剰ｿｰ縲・  {graded_on_failure or '・域裏鬚・ｮｾ・・}

隸ｷ逕滓・蛻帶э蛹也噪螟ｱ雍･蜷取棡縲りｧ・・・・- fumble・亥､ｧ螟ｱ雍･・牙錘譫懷ｺ疲・譏ｾ驥堺ｺ取勸騾・failure
- 驥崎ｯ墓ｬ｡謨ｰ雜雁､夲ｼ悟錘譫懆ｶ贋ｸ･驥・- 莨伜・扈灘粋蝨ｺ譎ｯ扈・鰍蜥瑚ｰ・衍蜻倡音雍ｨ隶ｾ隶｡蜷取棡
- 蜿ｯ蝨ｨ讓｡蝮鈴｢・ｮｾ螟ｱ雍･謠剰ｿｰ蝓ｺ遑荳頑黄螻墓・謾ｹ蜀・
霑泌屓 JSON・・{{
  "narrative": "螟ｱ雍･蜿吩ｺ区緒霑ｰ",
  "markup_effects": []
}}

蜿ｯ逕ｨ @譬・ｮｰ・域叛蜈･ markup_effects 謨ｰ扈・ｼ会ｼ・- @stat_change(stat_name="螻樊ｧ蜷・, delta=-1, narrative="邂遏ｭ蜴溷屏")
- @spawn_enemy(enemy_ref="謨御ｺｺ蜷・, scene="蝨ｺ譎ｯ蜷・, quantity=1)
- @npc_state_change(npc_name="NPC蜷・, new_state="譁ｰ迥ｶ諤・)
- @item_gain(item_name="迚ｩ蜩∝錐")
- @grant_weapon(weapon_ref="豁ｦ蝎ｨ蜷・, scene="蝨ｺ譎ｯ蜷・, quantity=1)

譌蜷磯よ・ｮｰ譌ｶ markup_effects 逡咏ｩｺ縲Ｏarrative 荳榊庄荳ｺ遨ｺ縲・逶ｴ謗･霎灘・ JSON縲・""
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "菴譏ｯ荳荳ｪTRPG隗・・霎・勧陬∝愛縲ゆｻ・ｾ灘・JSON縲・},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        max_tokens=800,
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    try:
        result = json.loads(raw)
        return {
            "narrative": result.get("narrative", ""),
            "markup_effects": result.get("markup_effects", []),
        }
    except json.JSONDecodeError:
        return {"narrative": graded_on_failure or f"{skill_name}譽螳壼､ｱ雍･縲・,
                "markup_effects": []}

def evaluate_soft_requirement(expr: str, inv_desc: str, scene_desc: str) -> dict:
    """LLM fallback for soft requirements (after ||).

    Evaluates narrative conditions like "隹・衍蜻俶戟譛牙・貅・ or "蟾ｲ遏･譎灘､ｧ蝌ｴ逧・ｭ伜惠"
    that cannot be resolved deterministically.

    Returns {"met": bool, "reason": str}
    """
    if not expr or not expr.strip():
        return {"met": True, "reason": ""}

    prompt = f"""菴譏ｯ TRPG 隗・・陬∝愛縲ょ愛譁ｭ蠖灘燕隹・衍蜻俶弍蜷ｦ貊｡雜ｳ扈吝ｮ夂噪蜿吩ｺ区擅莉ｶ縲・
縲占ｰ・衍蜻倥・  謠剰ｿｰ・嘴inv_desc or '・域裏・・}

縲仙惻譎ｯ縲・  {scene_desc or '・域裏・・}

縲先擅莉ｶ縲・  {expr}

譚｡莉ｶ莉・ｶ牙所蜿吩ｺ区ｧ蛻､譁ｭ・育黄蜩∵戟譛峨∫衍隸・憾諤√¨PC蜈ｳ邉ｻ遲会ｼ峨・闍･譚｡莉ｶ蜥瑚ｰ・衍蜻倡噪蠖灘燕迥ｶ蜀ｵ縲∝ｷｲ譛臥黄蜩∵・蟾ｲ遏･菫｡諱ｯ逶ｸ隨ｦ蛻吝愛螳壻ｸｺ貊｡雜ｳ縲・荳咲｡ｮ螳壽慮蛟ｾ蜷台ｺ主愛螳壻ｸｺ貊｡雜ｳ・磯∩蜈崎ｿ・ｺｦ蜊｡蜈ｳ・峨・
霑泌屓 JSON・・{{"met": true, "reason": "邂遏ｭ逅・罰"}}
謌・{{"met": false, "reason": "邂遏ｭ逅・罰"}}

逶ｴ謗･霎灘・ JSON縲・""
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "菴譏ｯ荳荳ｪTRPG隗・・陬∝愛縲ゆｻ・ｾ灘・JSON縲・},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=200,
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    try:
        result = json.loads(raw)
        return {"met": result.get("met", True), "reason": result.get("reason", "")}
    except json.JSONDecodeError:
        return {"met": True, "reason": "JSON隗｣譫仙､ｱ雍･・碁ｻ倩ｮ､騾夊ｿ・}


def evaluate_combat_round_narrative(
    round_log: list, enemies_desc: str,
    player_name: str, scene: str,
) -> dict:
    """Generate per-round immersive combat narrative via LLM."""
    from prompts import build_combat_narrative_prompt
    prompt = build_combat_narrative_prompt(round_log, enemies_desc, player_name, scene)
    try:
        return call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                            thinking=False, reasoning_effort="low",
                            fallback_schema={"narrative": "", "scene_hint": ""})
    except Exception:
        return {"narrative": "", "scene_hint": ""}
