"""
Builds the canonical 10-prompt library and JSON schemas directly from psychiatric_agent_architecture.md.
Preserves runtime anchors for Prompt 01 (Egyptian dialect lockdown, Aoede female persona, anti-glitch interruption rules).
"""

import os
import re
import json

base_dir = r"c:\sharing1\ML4\psychiatric_agent"
arch_file = os.path.join(base_dir, "psychiatric_agent_architecture.md")

with open(arch_file, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

# 1. Target files and directories
directories = [
    "prompts/live_agent",
    "prompts/safety",
    "prompts/memory",
    "prompts/clinical",
    "prompts/reporting",
    "prompts/transcription",
    "prompts/evaluation",
    "schemas"
]

for d in directories:
    os.makedirs(os.path.join(base_dir, d), exist_ok=True)

# 2. Extract Section 12 prompts
prompts_sec = text[text.find("# 12. Prompt Library"):text.find("# 13. Structured Output")]
pattern = r"##\s+Prompt\s+(\d+)\s+[^\w\s]+\s+([^\r\n]+)"
matches = list(re.finditer(pattern, prompts_sec))

extracted = {}
for i, m in enumerate(matches):
    p_num = m.group(1)
    p_name = m.group(2).strip()
    start = m.start()
    end = matches[i+1].start() if i+1 < len(matches) else len(prompts_sec)
    segment = prompts_sec[start:end].strip()

    # Model and inputs/outputs metadata
    meta_match = re.search(r"\*\*Model:\*\*(.*?)(?=```|\Z)", segment, re.DOTALL)
    metadata = ("**Model:**" + meta_match.group(1).strip()) if meta_match else ""

    # Code block
    code_match = re.search(r"```text\r?\n(.*?)\r?\n```", segment, re.DOTALL)
    prompt_body = code_match.group(1).strip() if code_match else segment

    extracted[p_num] = {
        "num": p_num,
        "name": p_name,
        "metadata": metadata,
        "body": prompt_body
    }

# 3. Enhance Prompt 01 to weave in Aoede voice lock, Egyptian dialect rules, and interruption rules
p1_base = extracted["01"]["body"]
p1_enhanced = f"""# هويتك الشخصية وصوتك المعتمد:
أنتِ "فضفضة" (Fadfada) — رفيقة استماع داعمة ومريحة نفسياً تتحدثين في جلسة صوتية حية بالعامية المصرية المعاصرة (Gemini 3.8 Live).
- اسمكِ: فضفضة (Fadfada).
- جنسكِ وصيغتكِ: أنثى (صوت Aoede المعتمد الوحيد). تحدثي بصيغة المؤنث لنفسك (أنا سامعاك، متفهمة، حاسة بيك). ممنوع تغيير الصوت أو استخدام نبرة رجالية نهائياً.

# إجبار اللهجة العامية المصرية الصارم (Strict Egyptian Dialect Enforcement):
- ⚠️ قاعدة إلزامية قطعية: تحدثي دائماً وحصرياً بالعامية المصرية الأصيلة المعاصرة بنسبة 100%.
- ❌ ممنوع التحدث باللغة الإنجليزية أو الرد بالإنجليزية، حتى لو تحدث المستخدم معك بالإنجليزية.
- ❌ ممنوع التحدث باللغة العربية الفصحى المتكلفة أو الإخبارية (مثل: "ماذا بك"، "هل تشعر بالحزن").
- ❌ ممنوع التحدث بأي لهجة عربية أخرى (لا خليجي، لا شامي، لا مغاربي).

# الاستثناء الوحيد للمصطلحات الإنجليزية:
- يُسمح فقط بنطق المصطلحات والكلمات الإنجليزية الشائعة في الحديث النفسي واليومي التي يصعب أو يثقل ترجمتها بالعربية الفصحى المتكلفة:
  (Overthinking, Burnout, Panic attack, Trigger, Stress, Trauma, Safe space, ADHD).
- عدا هذه الكلمات، كل جملة وسياق يجب أن يكون بالعامية المصرية الخالصة.

# أسلوب الحديث الصوتي ومواجهة المقاطعة:
- تحدثي بجمل صوتية قصيرة ودافئة (جملة أو جملتين فقط)، واطرحي سؤالاً واحداً فقط في كل دور.
- ❌ ممنوع إعادة الجواب من البداية بعد حدوث مقاطعة.
- إذا قاطعكِ المستخدم وتكلم، توقفي فوراً وركزي على الاستجابة المباشرة لكلمات المستخدم الجديدة دون تكرار أي مقاطع سابقة.

{p1_base}
"""

prompt_map = {
    "01": ("prompts/live_agent/system_prompt.md", p1_enhanced),
    "02": ("prompts/safety/safety_signal_analysis.md", extracted["02"]["body"]),
    "03": ("prompts/memory/memory_extractor.md", extracted["03"]["body"]),
    "04": ("prompts/memory/memory_reconciler.md", extracted["04"]["body"]),
    "05": ("prompts/reporting/detailed_session_report.md", extracted["05"]["body"]),
    "06": ("prompts/memory/session_context_builder.md", extracted["06"]["body"]),
    "07": ("prompts/clinical/therapeutic_protocol_selector.md", extracted["07"]["body"]),
    "08": ("prompts/reporting/patient_friendly_recap.md", extracted["08"]["body"]),
    "09": ("prompts/evaluation/quality_evaluator.md", extracted["09"]["body"]),
    "10": ("prompts/transcription/egyptian_arabic_normalizer.md", extracted["10"]["body"]),
}

for num, (rel_path, content) in prompt_map.items():
    file_path = os.path.join(base_dir, rel_path)
    meta = extracted[num]["metadata"]
    name = extracted[num]["name"]
    full_doc = f"""# Prompt {num} — {name}

{meta}

```text
{content}
```
"""
    # For system_prompt.md, write the direct markdown instruction text cleanly
    if num == "01":
        with open(file_path, "w", encoding="utf-8") as out:
            out.write(content)
    else:
        with open(file_path, "w", encoding="utf-8") as out:
            out.write(full_doc)

    print(f"Wrote Prompt {num} to {rel_path} ({len(full_doc)} bytes)")

# 4. Extract Section 13 schemas and write them to schemas/
s13 = text[text.find("# 13. Structured Output"):text.find("# 14. Function Calling")]

schemas = {
    "schemas/patient_memory.schema.json": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "CandidateMemoryProposal",
        "description": "Structured candidate memory extracted from psychiatric session conforming to Section 13.1",
        "type": "object",
        "properties": {
            "patient_id": {"type": "string"},
            "session_id": {"type": "string"},
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "coping_preference",
                                "communication_preference",
                                "patient_goal",
                                "personal_history",
                                "symptom_report",
                                "treatment_report",
                                "support_system",
                                "boundary"
                            ]
                        },
                        "content": {"type": "string"},
                        "source_type": {
                            "type": "string",
                            "enum": ["patient_reported", "clinician_supplied", "session_observation"]
                        },
                        "source_event_ids": {"type": "array", "items": {"type": "string"}},
                        "supporting_evidence": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "sensitivity": {
                            "type": "string",
                            "enum": ["standard", "review_required", "strictly_confidential"]
                        },
                        "time_sensitive": {"type": "boolean"},
                        "proposed_action": {
                            "type": "string",
                            "enum": ["ADD", "UPDATE", "NO_ACTION", "REJECT", "ERASE"]
                        },
                        "requires_patient_confirmation": {"type": "boolean"},
                        "reason_for_retention": {"type": "string"}
                    },
                    "required": ["memory_type", "content", "source_type", "confidence", "proposed_action"]
                }
            },
            "excluded_items": {"type": "array", "items": {"type": "string"}},
            "clarifications_needed": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["patient_id", "session_id", "proposals"]
    },
    "schemas/safety_signal.schema.json": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "SafetySignalAnalysis",
        "description": "Structured clinical safety signal evaluation conforming to Section 13.2",
        "type": "object",
        "properties": {
            "signal_categories": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "none",
                        "ambiguous",
                        "suicide_risk",
                        "self_harm_concern",
                        "severe_violence",
                        "acute_distress",
                        "overdose_medical_emergency",
                        "coercion_unsafe_environment"
                    ]
                }
            },
            "supporting_evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "evidence_type": {
                            "type": "string",
                            "enum": ["direct_patient_statement", "inferred_pattern", "third_party_reference"]
                        },
                        "quote_or_description": {"type": "string"}
                    },
                    "required": ["evidence_type", "quote_or_description"]
                }
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "recommended_action": {
                "type": "string",
                "enum": [
                    "continue_support",
                    "explore_safety_softly",
                    "provide_hotline_resources",
                    "escalate_immediate_crisis"
                ]
            },
            "emergency_action": {"type": "boolean"},
            "suggested_hotlines": {"type": "array", "items": {"type": "string"}},
            "reasoning_ar": {"type": "string"}
        },
        "required": ["signal_categories", "confidence", "recommended_action", "emergency_action"]
    },
    "schemas/session_report.schema.json": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "DetailedSessionReport",
        "description": "Detailed clinical longitudinal support report conforming to Section 13.3",
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "patient_id": {"type": "string"},
            "session_metadata": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "duration_seconds": {"type": "number"},
                    "turn_count": {"type": "integer"}
                }
            },
            "primary_concerns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "severity_patient_reported": {"type": "string"},
                        "evidence": {"type": "string"}
                    },
                    "required": ["topic", "evidence"]
                }
            },
            "emotional_state_observed": {
                "type": "object",
                "properties": {
                    "patient_described": {"type": "string"},
                    "tentative_reflection": {"type": "string"}
                }
            },
            "interventions_used": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "protocol_id": {"type": "string"},
                        "name": {"type": "string"},
                        "patient_response": {"type": "string"}
                    },
                    "required": ["name", "patient_response"]
                }
            },
            "patient_strengths_and_resources": {"type": "array", "items": {"type": "string"}},
            "collaborative_next_steps": {"type": "array", "items": {"type": "string"}},
            "safety_assessment_summary": {
                "type": "object",
                "properties": {
                    "risk_detected": {"type": "boolean"},
                    "details": {"type": "string"}
                },
                "required": ["risk_detected"]
            },
            "patient_friendly_summary_ar": {"type": "string"}
        },
        "required": [
            "session_id",
            "patient_id",
            "primary_concerns",
            "interventions_used",
            "safety_assessment_summary",
            "patient_friendly_summary_ar"
        ]
    }
}

for rel_path, schema_obj in schemas.items():
    file_path = os.path.join(base_dir, rel_path)
    with open(file_path, "w", encoding="utf-8") as out:
        json.dump(schema_obj, out, indent=2, ensure_ascii=False)
    print(f"Wrote schema to {rel_path} ({os.path.getsize(file_path)} bytes)")

print("Canonical prompts and schemas built successfully!")
