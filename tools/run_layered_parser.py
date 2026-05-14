"""
Run the layered parser against the actual module content.
Produces real L1/L2/L3 JSON via LLM calls.
"""
import sys, os, json, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils import parser as parse_docx, estimate_and_truncate_context
from module_designer import parse_module, save_module, run_pipeline, validate_all
from library import WeaponLibrary, EnemyLibrary, ContentInjector
from llm import call_deepseek

# ── Load content ──
DOCX_PATH = os.path.join(os.path.dirname(__file__), "..", "常暗之厢（7版规则，简体修正版）.docx")
print("Loading module content...")
content = parse_docx(DOCX_PATH)
content = estimate_and_truncate_context(content)
print(f"Content loaded: {len(content)} chars")

# ── Init libraries ──
print("Initializing libraries...")
wl = WeaponLibrary()
wl.load_core()
el = EnemyLibrary()
el.load_core()
injector = ContentInjector(wl, el)
print(f"Weapons: {len(wl)}, Enemies: {len(el)}")

# ── LLM adapter ──
def llm_parse(prompt_text: str, system: str = None) -> dict:
    return call_deepseek(prompt_text, system=system, json_mode=True)

# ── Run layered parser ──
MODULE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢")
os.makedirs(MODULE_DIR, exist_ok=True)

print("\n" + "=" * 60)
print("Starting layered parser (3 LLM calls)...")
print("=" * 60)

results = parse_module(content, llm_parse, verbose=True)

# ── Save raw results ──
print("\nSaving raw parse results...")
save_module(results, MODULE_DIR)

# ── Schema validation ──
print("\n" + "=" * 60)
print("Schema Validation Report")
print("=" * 60)
reports = validate_all(results["L1"], results["L2"], results["L3"])
for layer, report in reports.items():
    status = "PASS" if report.is_valid else "ISSUES"
    print(f"{layer} [{status}]: {report.summary()}")

# ── Run pipeline ──
print("\n" + "=" * 60)
print("Pipeline (inject + cross-validate)")
print("=" * 60)
pipeline_result = run_pipeline(
    results["L1"], results["L2"], results["L3"],
    injector=injector, weapon_lib=wl, enemy_lib=el,
    verbose=True,
)
print("\n" + pipeline_result.summary())

# ── Save final ──
FINAL_DIR = os.path.join(MODULE_DIR, "final")
os.makedirs(FINAL_DIR, exist_ok=True)
for layer_name, key in [("L1", "l1_player"), ("L2", "l2_keeper"), ("L3", "l3_designer")]:
    data = getattr(pipeline_result, f"{layer_name.lower()}_data")
    path = os.path.join(FINAL_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  {layer_name} -> {path}")

# ── Summary ──
print("\n" + "=" * 60)
print("Done")
print("=" * 60)
print(f"L1: {len(results['L1'])} scenes")
print(f"L2: {len(results['L2'].get('scenes', {}))} scenes, {len(results['L2'].get('events', []))} events")
l3 = results["L3"]
print(f"L3: {len(l3.get('world_rules', []))} world rules, {len(l3.get('logic_chains', []))} logic chains")
print(f"L3: {len(l3.get('scene_intents', {}))} scene intents, {len(l3.get('ending_conditions', []))} endings")
print(f"Pipeline: {'PASS' if pipeline_result.all_valid else 'HAS_ISSUES'}")
print(f"Files saved to: {MODULE_DIR}/")
