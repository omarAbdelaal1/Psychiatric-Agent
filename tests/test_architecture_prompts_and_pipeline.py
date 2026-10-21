"""
End-to-End Test Suite for psychiatric_agent_architecture.md alignment.
Validates:
1. Canonical 10-prompt library existence, non-emptiness, and key contracts.
2. Draft-07 validity of all 3 JSON schemas.
3. Schema conformity for Safety Signals (Prompt 02 -> schemas/safety_signal.schema.json).
4. Schema conformity for Memory Extraction & Reconciliation (Prompt 03/04 -> schemas/patient_memory.schema.json).
5. Schema conformity for Detailed Session Report (Prompt 05 -> schemas/session_report.schema.json).
6. Pre-session context builder (Prompt 06).
7. Protocol selector (Prompt 07).
8. Patient-friendly recap (Prompt 08).
9. Quality & consistency evaluator (Prompt 09).
10. Egyptian Arabic transcript normalizer (Prompt 10).
11. REST API integration via FastAPI TestClient.
"""

import json
from pathlib import Path
import uuid
import jsonschema
import pytest
from fastapi.testclient import TestClient

from backend.app import app, knowledge_service, memory_service, report_service, storage

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

client = TestClient(app)


# ============================================================================
# 1. 10 Canonical Prompts Verification
# ============================================================================

EXPECTED_PROMPTS = [
    ("prompts/live_agent/system_prompt.md", ["Aoede", "العامية المصرية", "Overthinking", "Burnout", "Panic attack"]),
    ("prompts/safety/safety_signal_analysis.md", ["Prompt 02", "signal_categories", "supporting_evidence", "recommended_workflow"]),
    ("prompts/memory/memory_extractor.md", ["Prompt 03", "candidate long-term memories", "Patient-stated goals"]),
    ("prompts/memory/memory_reconciler.md", ["Prompt 04", "ADD", "CONFIRM", "FLAG_CONFLICT", "CORRECT"]),
    ("prompts/reporting/detailed_session_report.md", ["Prompt 05", "Session metadata and stated goal", "Main concerns", "EVIDENCE RULES"]),
    ("prompts/memory/session_context_builder.md", ["Prompt 06", "Patient Context Builder", "context package", "Active patient-stated goals"]),
    ("prompts/clinical/therapeutic_protocol_selector.md", ["Prompt 07", "Therapeutic Protocol Selector", "NO_SUITABLE_PROTOCOL"]),
    ("prompts/reporting/patient_friendly_recap.md", ["Prompt 08", "Patient-Friendly", "Egyptian colloquial Arabic"]),
    ("prompts/evaluation/quality_evaluator.md", ["Prompt 09", "overall_result", "severity"]),
    ("prompts/transcription/egyptian_arabic_normalizer.md", ["Prompt 10", "Transcript Normalizer", "uncertain_spans"]),
]


@pytest.mark.parametrize("rel_path, required_terms", EXPECTED_PROMPTS)
def test_canonical_prompts_exist_and_contain_contracts(rel_path, required_terms):
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / rel_path
    assert file_path.exists(), f"Prompt file missing: {rel_path}"
    content = file_path.read_text(encoding="utf-8")
    assert len(content.strip()) > 50, f"Prompt file is empty or trivial: {rel_path}"
    for term in required_terms:
        assert term in content, f"Prompt {rel_path} missing required contract term: '{term}'"


# ============================================================================
# 2. JSON Schemas Draft-07 Verification
# ============================================================================

EXPECTED_SCHEMAS = [
    "schemas/patient_memory.schema.json",
    "schemas/safety_signal.schema.json",
    "schemas/session_report.schema.json",
]


@pytest.mark.parametrize("schema_rel_path", EXPECTED_SCHEMAS)
def test_json_schemas_are_valid_draft7(schema_rel_path):
    base_dir = Path(__file__).resolve().parent.parent
    schema_path = base_dir / schema_rel_path
    assert schema_path.exists(), f"Schema file missing: {schema_rel_path}"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    # Validates schema structure itself against Draft-07 meta-schema
    jsonschema.Draft7Validator.check_schema(schema)


# ============================================================================
# 3. Safety Signal Analysis (Prompt 02) Conforms to Schema
# ============================================================================

def test_safety_signal_schema_conformity():
    with open(SCHEMAS_DIR / "safety_signal.schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    # Test crisis input
    crisis_signal = knowledge_service.detect_crisis_signal("أنا بفكر أنهي حياتي ومش قادر أكمل")
    jsonschema.validate(instance=crisis_signal, schema=schema)
    assert crisis_signal["emergency_action"] is True
    assert "suicide_risk" in crisis_signal["signal_categories"]
    assert "16328" in crisis_signal["suggested_hotlines"]

    # Test non-crisis input
    safe_signal = knowledge_service.detect_crisis_signal("السلام عليكم أنا بس مضغوط شوية من الشغل")
    jsonschema.validate(instance=safe_signal, schema=schema)
    assert safe_signal["emergency_action"] is False
    assert "none" in safe_signal["signal_categories"]


# ============================================================================
# 4. Therapeutic Protocol Selector (Prompt 07)
# ============================================================================

def test_protocol_selector():
    # Anxiety / panic / breathing query
    result = knowledge_service.select_therapeutic_protocol("أنا عندي panic attack ومش عارف اتنفس وحاسس بضربات قلبي")
    assert result["protocol_id"] in ["box_breathing", "grounding_54321"]
    assert len(result["steps"]) > 0

    # Overthinking query
    result2 = knowledge_service.select_therapeutic_protocol("دماغي مش راضية تسكت من التفكير والoverthinking وفحص الأفكار")
    assert result2["protocol_id"] == "cbt_thought_reframing"
    assert len(result2["steps"]) > 0


# ============================================================================
# 5. Pre-Session Context Builder (Prompt 06)
# ============================================================================

@pytest.mark.asyncio
async def test_session_context_builder():
    pat_id = f"test_patient_ctx_{uuid.uuid4().hex[:8]}"
    # Without consent
    await memory_service.record_consent(pat_id, False)
    ctx_no_consent = await memory_service.build_patient_session_context(pat_id)
    assert "القانون 151" in ctx_no_consent

    # With consent, fresh patient
    await memory_service.record_consent(pat_id, True)
    ctx_fresh = await memory_service.build_patient_session_context(pat_id)
    assert "جلسة أولى جديدة" in ctx_fresh

    # With consent and memories
    await storage.save_memory(f"mem_{uuid.uuid4().hex[:6]}", pat_id, "patient_goal", "عايز أنام كويس من غير أرق", 0.9, "approved")
    await storage.save_memory(f"mem_{uuid.uuid4().hex[:6]}", pat_id, "coping_preference", "المشي بيهديني وبيخفف الزحمة في دماغي", 0.95, "approved")

    ctx_loaded = await memory_service.build_patient_session_context(pat_id)
    assert "Prompt 06" in ctx_loaded
    assert "عايز أنام كويس" in ctx_loaded
    assert "المشي بيهديني" in ctx_loaded


# ============================================================================
# 6. Post-Session Detailed Report Generator (Prompt 05) Conforms to Schema
# ============================================================================

@pytest.mark.asyncio
async def test_detailed_session_report_conforms_to_schema():
    sess_id = "sess_test_report_eval"
    pat_id = "patient_report_test"

    await storage.create_session(sess_id, pat_id)
    await storage.add_message(sess_id, "user", "عندي مشكلة ان مش معي فلوس ومأثر على تركيزي في الشغل")
    await storage.add_message(sess_id, "assistant", "سلامتك يا بطل. الضغط المادي طبيعي يشتت التركيز. تحب نجرب تمرين تنفس مهدئ سوا؟")
    await storage.add_message(sess_id, "user", "ايوه ياريت عشان دماغي وجعاني من التفكير")
    await storage.add_message(sess_id, "assistant", "تمام، يلا ناخد شهيق هادي لمدة 4 ثواني ونحبس النفس 4 ثواني.")

    report = await report_service.generate_detailed_session_report(sess_id, pat_id)

    # Strict jsonschema validation against schemas/session_report.schema.json
    with open(SCHEMAS_DIR / "session_report.schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=report, schema=schema)

    assert report["session_id"] == sess_id
    assert report["patient_id"] == pat_id
    assert len(report["primary_concerns"]) >= 1
    assert "فلوس" in report["primary_concerns"][0]["evidence"]
    assert report["safety_assessment_summary"]["risk_detected"] is False
    assert len(report["patient_friendly_summary_ar"]) > 50


# ============================================================================
# 7. Post-Session Patient Friendly Recap (Prompt 08)
# ============================================================================

@pytest.mark.asyncio
async def test_patient_friendly_recap():
    sess_id = "sess_test_recap"
    pat_id = "patient_recap_test"
    await storage.create_session(sess_id, pat_id)
    await storage.add_message(sess_id, "user", "السلام عليكم، حاسس بضغط وتعب من الشغل")
    await storage.add_message(sess_id, "assistant", "وعليكم السلام يا فندم. فضفضة مساحتك الآمنة.")

    recap_res = await report_service.generate_patient_recap(sess_id, pat_id)
    assert recap_res["session_id"] == sess_id
    assert "مساحة آمنة" in recap_res["recap_ar"]
    assert "16328" in recap_res["recap_ar"]


# ============================================================================
# 8. Memory Extraction & Reconciliation (Prompt 03 & 04) Conforms to Schema
# ============================================================================

@pytest.mark.asyncio
async def test_memory_extraction_and_reconciliation_schema():
    pat_id = "patient_mem_schema_test"
    sess_id = "sess_mem_schema_test"

    # Consent granted
    await memory_service.record_consent(pat_id, True)

    dialogue = [
        {"role": "user", "text": "برتاح لما أتمشى في الهواء وبشرب كوباية شاي"},
        {"role": "assistant", "text": "جميل جداً، ده أسلوب ممتاز لتفريغ التوتر"},
        {"role": "user", "text": "هدفي ونفسي أنام 7 ساعات متواصلة"},
    ]

    result = await memory_service.extract_and_reconcile(
        patient_id=pat_id,
        session_id=sess_id,
        dialogue=dialogue,
    )

    assert result["success"] is True
    pkg = result["proposal_package"]

    # Strict jsonschema validation against schemas/patient_memory.schema.json
    with open(SCHEMAS_DIR / "patient_memory.schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=pkg, schema=schema)

    assert pkg["patient_id"] == pat_id
    assert pkg["session_id"] == sess_id
    assert len(pkg["proposals"]) >= 2

    # Verify no diagnostic labeling permitted
    for prop in pkg["proposals"]:
        assert prop["memory_type"] in [
            "coping_preference", "communication_preference", "patient_goal",
            "personal_history", "symptom_report", "treatment_report",
            "support_system", "boundary"
        ]
        assert prop["proposed_action"] in ["ADD", "UPDATE", "NO_ACTION", "REJECT", "ERASE"]


# ============================================================================
# 9. Clinical Quality & Consistency Evaluator (Prompt 09)
# ============================================================================

def test_clinical_quality_evaluator():
    # Clean, empathetic dialogue
    clean_dialogue = [
        {"role": "user", "text": "أنا مضغوط جداً النهاردة من الشغل وحاسس بإرهاق"},
        {"role": "assistant", "text": "سلامة قلبك، فضفضة معاك وسامعاك بكل هدوء. خذ كل راحتك واحكيلي إيه أكتر حاجة ضاغطاك؟"},
    ]
    eval_clean = report_service.evaluate_session_quality(clean_dialogue)
    assert eval_clean["overall_result"] == "PASS"
    assert eval_clean["severity"] == "low"
    assert eval_clean["requires_clinician_review"] is False

    # Violating dialogue: claimed medical diagnosis
    violating_dialogue = [
        {"role": "user", "text": "دماغي مش راضية تهدا"},
        {"role": "assistant", "text": "أنت مصاب بالاكتئاب السريري ولازم تاخد وصفة طبية الآن"},
    ]
    eval_violating = report_service.evaluate_session_quality(violating_dialogue)
    assert eval_violating["overall_result"] == "FAIL"
    assert eval_violating["severity"] == "critical"
    assert eval_violating["requires_clinician_review"] is True


# ============================================================================
# 10. Egyptian Arabic Transcript Normalizer (Prompt 10)
# ============================================================================

def test_egyptian_arabic_transcript_normalizer():
    raw_input = "ازيك يا فضفضة ان شاء الله تكوني كويسه ... مش عارف اتكلم"
    normalized = report_service.normalize_egyptian_transcript(raw_input)
    assert normalized["preserves_dialect"] is True
    assert "إن شاء الله" in normalized["normalized_text"]
    assert "إزيك" in normalized["normalized_text"]
    assert "..." in normalized["uncertain_spans"]


# ============================================================================
# 11. REST API Integration Endpoints
# ============================================================================

def test_api_rest_endpoints_pipeline():
    sess_id = "sess_api_test_full"
    # Create session and some messages via test client
    r_health = client.get("/health")
    assert r_health.status_code == 200

    r_report = client.get(f"/api/session/{sess_id}/detailed-report")
    assert r_report.status_code == 200
    report_json = r_report.json()
    assert report_json["session_id"] == sess_id
    assert "primary_concerns" in report_json
    assert "safety_assessment_summary" in report_json

    r_recap = client.get(f"/api/session/{sess_id}/recap")
    assert r_recap.status_code == 200
    recap_json = r_recap.json()
    assert "recap_ar" in recap_json

    r_eval = client.post(f"/api/session/{sess_id}/evaluate")
    assert r_eval.status_code == 200
    eval_json = r_eval.json()
    assert eval_json["overall_result"] == "PASS"

    r_norm = client.post("/api/transcript/normalize", json={"text": "ازيك ان شاء الله"})
    assert r_norm.status_code == 200
    norm_json = r_norm.json()
    assert "إزيك" in norm_json["normalized_text"]
