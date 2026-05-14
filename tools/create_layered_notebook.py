"""Create parser_layered.ipynb — clean layered-only notebook."""
import json

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {},
    "cells": [
        # Cell 0: Title markdown
        {
            "cell_type": "markdown",
            "id": "title",
            "metadata": {},
            "source": [
                "# 常暗之厢 — 三层解析工作流\n",
                "\n",
                "**新流程**：source.txt → `layered_parser.parse_module()` → `layered_pipeline.run_pipeline()` → L1+L2+L3 JSON\n",
                "\n",
                "旧 `parsers.py` / `pipeline.py` 已废弃，此 notebook 只使用新的三层解析器。\n",
                "\n",
                "**注意**：需要 DeepSeek API 可用。每次 LLM 调用消耗 token（三个 layer 共 3 次调用）。"
            ],
        },
        # Cell 1: Imports
        {
            "cell_type": "code",
            "id": "imports",
            "metadata": {},
            "source": [
                "import sys\n",
                "import json\n",
                "import os\n",
                "\n",
                "sys.path.insert(0, \"../src\")\n",
                "\n",
                "from utils import parser, estimate_and_truncate_context\n",
                "from module_designer import (\n",
                "    parse_module, save_module,\n",
                "    run_pipeline,\n",
                "    validate_all,\n",
                ")\n",
                "from library import WeaponLibrary, EnemyLibrary, ContentInjector\n",
                "from llm import call_deepseek"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 2: Load content
        {
            "cell_type": "code",
            "id": "load-content",
            "metadata": {},
            "source": [
                "content = parser(\"../常暗之厢（7版规则，简体修正版）.docx\")\n",
                "content = estimate_and_truncate_context(content)"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 3: Init library
        {
            "cell_type": "code",
            "id": "init-library",
            "metadata": {},
            "source": [
                "# 初始化武器库、敌人库、注入器\n",
                "wl = WeaponLibrary()\n",
                "wl.load_core()\n",
                "el = EnemyLibrary()\n",
                "el.load_core()\n",
                "injector = ContentInjector(wl, el)\n",
                "\n",
                "print(f\"武器库：{len(wl)} 件\")\n",
                "print(f\"敌人库：{len(el)} 个\")\n",
                "print(f\"注入器：{'就绪' if injector else '未初始化'}\")"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 4: LLM wrapper
        {
            "cell_type": "code",
            "id": "llm-wrapper",
            "metadata": {},
            "source": [
                "# parse_module 需要的 llm_call 签名：(prompt, system) -> dict\n",
                "# call_deepseek 签名：(prompt, *, json_mode, system, ...)\n",
                "def llm_parse(prompt_text: str, system: str = None) -> dict:\n",
                "    \"\"\"适配器：将 call_deepseek 包装为 parse_module 需要的签名.\"\"\"\n",
                "    return call_deepseek(prompt_text, system=system, json_mode=True)"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 5: Run layered parser
        {
            "cell_type": "code",
            "id": "run-parser",
            "metadata": {},
            "source": [
                "MODULE_DIR = \"../data/modules/常暗之厢\"\n",
                "\n",
                "# 一键解析：source.txt → L1 + L2 + L3\n",
                "results = parse_module(content, llm_parse, verbose=True)\n",
                "\n",
                "# 保存原始解析结果\n",
                "os.makedirs(MODULE_DIR, exist_ok=True)\n",
                "save_module(results, MODULE_DIR)\n",
                "print(f\"\\n原始解析结果已保存至 {MODULE_DIR}/\")"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 6: Schema validation report
        {
            "cell_type": "code",
            "id": "schema-validation",
            "metadata": {},
            "source": [
                "# Schema 验证\n",
                "print(\"=\" * 60)\n",
                "print(\"Schema 验证报告\")\n",
                "print(\"=\" * 60)\n",
                "reports = validate_all(results[\"L1\"], results[\"L2\"], results[\"L3\"])\n",
                "for layer, report in reports.items():\n",
                "    status = \"PASS\" if report.is_valid else \"ISSUES\"\n",
                "    print(f\"\\n{layer} [{status}]:\")\n",
                "    print(f\"  {report.summary()}\")"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 7: Run pipeline
        {
            "cell_type": "code",
            "id": "run-pipeline",
            "metadata": {},
            "source": [
                "# 后处理管线：注入 + 交叉引用验证\n",
                "pipeline_result = run_pipeline(\n",
                "    results[\"L1\"], results[\"L2\"], results[\"L3\"],\n",
                "    injector=injector, weapon_lib=wl, enemy_lib=el,\n",
                "    verbose=True,\n",
                ")\n",
                "\n",
                "print()\n",
                "print(pipeline_result.summary())"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 8: Save final output
        {
            "cell_type": "code",
            "id": "save-final",
            "metadata": {},
            "source": [
                "# 保存管线处理后的最终结果\n",
                "final_dir = os.path.join(MODULE_DIR, \"final\")\n",
                "os.makedirs(final_dir, exist_ok=True)\n",
                "\n",
                "for layer, data in [(\"L1\", pipeline_result.l1_data), (\"L2\", pipeline_result.l2_data), (\"L3\", pipeline_result.l3_data)]:\n",
                "    filename = f\"{layer.lower()}_player.json\" if layer == \"L1\" else f\"{layer.lower()}_keeper.json\" if layer == \"L2\" else f\"{layer.lower()}_designer.json\"\n",
                "    path = os.path.join(final_dir, filename)\n",
                "    with open(path, \"w\", encoding=\"utf-8\") as f:\n",
                "        json.dump(data, f, ensure_ascii=False, indent=2)\n",
                "    print(f\"{layer} -> {path}\")\n",
                "\n",
                "print(f\"\\n管线处理后结果已保存至 {final_dir}/\")"
            ],
            "outputs": [],
            "execution_count": None,
        },
        # Cell 9: Summary
        {
            "cell_type": "code",
            "id": "summary",
            "metadata": {},
            "source": [
                "print(\"=\" * 60)\n",
                "print(\"三层解析完成\")\n",
                "print(\"=\" * 60)\n",
                "print(f\"L1: {len(results['L1'])} 个场景\")\n",
                "print(f\"L2: {len(results['L2'].get('scenes', {}))} 个场景, {len(results['L2'].get('events', []))} 个事件\")\n",
                "print(f\"L3: {len(results['L3'].get('world_rules', []))} 条世界规则, {len(results['L3'].get('logic_chains', []))} 条逻辑链\")\n",
                "print(f\"L3: {len(results['L3'].get('scene_intents', {}))} 个场景意图\")\n",
                "print(f\"L3: {len(results['L3'].get('ending_conditions', []))} 个结局条件\")\n",
                "print(f\"\\n管线状态: {'PASS' if pipeline_result.all_valid else 'HAS_ISSUES'}\")"
            ],
            "outputs": [],
            "execution_count": None,
        },
    ],
}

with open("notebooks/parser_layered.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
print("Created notebooks/parser_layered.ipynb")
