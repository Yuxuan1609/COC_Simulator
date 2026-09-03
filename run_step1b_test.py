"""Run Step 1b only on 深渊之口 module."""
import sys, os, json
sys.path.insert(0, "src")

from llm import call_deepseek, set_llm_log_dir
from prompts import set_prompt_log_dir, set_current_round
from module_designer.layered_parser import build_step1b_prompt, STEP1B_SYSTEM
from datetime import datetime

# Log setup
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
log_dir = f"data/debug/step1b_test/{ts}"
os.makedirs(log_dir, exist_ok=True)
set_prompt_log_dir(log_dir)
set_llm_log_dir(log_dir)
set_current_round(0)

# Load module
module_path = "data/modules/深渊之口/module_raw.txt"
with open(module_path, "r", encoding="utf-8") as f:
    content = f.read()

print(f"模块长度: {len(content)} 字符")
print(f"日志目录: {log_dir}")

# Build prompt
prompt = build_step1b_prompt(content)
print(f"Prompt 长度: {len(prompt)} 字符")

# Save prompt
with open(os.path.join(log_dir, "step1b_prompt.txt"), "w", encoding="utf-8") as f:
    f.write(prompt)

# Call LLM
print("正在调用 LLM (Step 1b — 精修模组)...")
result = call_deepseek(
    prompt,
    json_mode=False,
    system=STEP1B_SYSTEM,
    model="deepseek-v4-flash-vision-exp",
    reasoning_effort="max",
)

# Save result
with open(os.path.join(log_dir, "step1b_result.txt"), "w", encoding="utf-8") as f:
    f.write(result)
print(f"结果长度: {len(result)} 字符")
print(f"结果已保存至 {log_dir}")
