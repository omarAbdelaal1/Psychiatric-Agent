import os
import re
import sys
import json

base_dir = r"c:\sharing1\ML4\psychiatric_agent"
arch_file = os.path.join(base_dir, "psychiatric_agent_architecture.md")

with open(arch_file, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

# Section 12 Prompts
prompts_sec = text[text.find("# 12. Prompt Library"):text.find("# 13. Structured Output")]

# Map Prompt numbers to target paths
prompt_targets = {
    "01": "prompts/live_agent/system_prompt.md",
    "02": "prompts/safety/safety_signal_analysis.md",
    "03": "prompts/memory/memory_extractor.md",
    "04": "prompts/memory/memory_reconciler.md",
    "05": "prompts/reporting/detailed_session_report.md",
    "06": "prompts/memory/session_context_builder.md",
    "07": "prompts/clinical/therapeutic_protocol_selector.md",
    "08": "prompts/reporting/patient_friendly_recap.md",
    "09": "prompts/evaluation/quality_evaluator.md",
    "10": "prompts/transcription/egyptian_arabic_normalizer.md",
}

# Regex to split on "## Prompt XX"
pattern = r"##\s+Prompt\s+(\d+)\s+[^\w\s]+\s+([^\r\n]+)"
matches = list(re.finditer(pattern, prompts_sec))

extracted = {}
for i, m in enumerate(matches):
    p_num = m.group(1)
    p_name = m.group(2).strip()
    start = m.start()
    end = matches[i+1].start() if i+1 < len(matches) else len(prompts_sec)
    segment = prompts_sec[start:end]
    
    # Extract code block if present
    code_match = re.search(r"```text\r?\n(.*?)\r?\n```", segment, re.DOTALL)
    prompt_body = code_match.group(1) if code_match else segment
    extracted[p_num] = {
        "name": p_name,
        "segment": segment,
        "body": prompt_body
    }
    print(f"Prompt {p_num}: {p_name} -> {len(prompt_body)} characters")

print(f"Total extracted: {len(extracted)} prompts")
