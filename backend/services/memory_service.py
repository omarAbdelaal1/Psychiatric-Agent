"""
Memory Extraction & Reconciliation Service for Fadfada Psychiatric Agent.
Enforces:
- Prompt 03: Patient Memory Extractor (Candidate proposals)
- Prompt 04: Memory Reconciliation (ADD, UPDATE, NO_ACTION, REJECT, ERASE)
- Schema: schemas/patient_memory.schema.json
- Egyptian Personal Data Protection Law No. 151/2020:
  - Strict consent requirement before extracting or storing longitudinal patient memories.
  - 8 permitted non-diagnostic domains.
  - Right to Erasure (شطب البيانات).
"""

import json
import logging
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional
import jsonschema

from backend.storage import SimpleStorage

logger = logging.getLogger("fadfada.memory")

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
MEMORY_SCHEMA_PATH = SCHEMAS_DIR / "patient_memory.schema.json"

ALLOWED_CATEGORIES = {
    "coping_preference",
    "communication_preference",
    "patient_goal",
    "personal_history",
    "symptom_report",
    "treatment_report",
    "support_system",
    "boundary",
}

# Forbidden clinical diagnosis indicators to prevent improper medical labeling
FORBIDDEN_DIAGNOSES = [
    "اضطراب ثنائي القطب",
    "bipolar",
    "اكتئاب حاد",
    "major depressive",
    "فصام",
    "schizophrenia",
    "وسواس قهري مرضي",
    "borderline",
    "حالة سريرية",
]


class MemoryService:
    def __init__(self, storage: SimpleStorage):
        self.storage = storage
        self._schema = self._load_schema()

    def _load_schema(self) -> Dict[str, Any]:
        if not MEMORY_SCHEMA_PATH.exists():
            raise FileNotFoundError(f"Patient memory schema not found at: {MEMORY_SCHEMA_PATH}")
        with open(MEMORY_SCHEMA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    async def check_consent(self, patient_id: str) -> bool:
        """Verifies if explicit consent was granted under Law 151/2020."""
        return await self.storage.get_consent(patient_id, "long_term_memory")

    async def record_consent(self, patient_id: str, granted: bool) -> Dict[str, Any]:
        """Records or revokes patient consent."""
        await self.storage.set_consent(patient_id, "long_term_memory", granted)
        return {
            "patient_id": patient_id,
            "consent_type": "long_term_memory",
            "granted": granted,
            "governing_law": "Egyptian Law No. 151/2020 on Personal Data Protection",
        }

    async def extract_and_reconcile(
        self,
        patient_id: str,
        session_id: str,
        dialogue: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Extracts candidate memories conforming to Prompt 03 & Prompt 04 and validates
        against schemas/patient_memory.schema.json.
        Refuses storage if consent has not been granted under Law 151/2020.
        """
        # 1. Gather dialogue if not passed directly
        if dialogue is None:
            messages = await self.storage.get_messages(session_id)
            dialogue = [{"role": m["role"], "text": m["text"]} for m in messages]

        # 2. Check consent under Law 151/2020
        has_consent = await self.check_consent(patient_id)
        if not has_consent:
            logger.info(f"Memory extraction refused for {patient_id}: Law 151/2020 consent withheld.")
            result_payload = {
                "patient_id": patient_id,
                "session_id": session_id,
                "proposals": [],
                "excluded_items": [
                    "تم استبعاد حفظ الذاكرة الطولية لعدم توفر موافقة صريحة وفقاً للقانون 151 لسنة 2020."
                ],
                "clarifications_needed": [],
            }
            jsonschema.validate(instance=result_payload, schema=self._schema)
            return {
                "success": False,
                "reason": "CONSENT_WITHHELD",
                "message_ar": "لم يتم تسجيل موافقة صريحة لحفظ الذاكرة وفقاً للقانون المصري رقم 151 لسنة 2020 لحماية البيانات الشخصية.",
                "proposal_package": result_payload,
            }

        if not dialogue:
            result_payload = {
                "patient_id": patient_id,
                "session_id": session_id,
                "proposals": [],
                "excluded_items": ["لا توجد رسائل مسجلة في الجلسة لاستخراج معلومات منها."],
                "clarifications_needed": [],
            }
            jsonschema.validate(instance=result_payload, schema=self._schema)
            return {
                "success": True,
                "proposal_package": result_payload,
                "memories_processed": [],
                "message": "No dialogue turns to extract.",
            }

        # 3. Extract candidate proposals conforming to Prompt 03
        raw_candidates = self._extract_candidates_from_dialogue(dialogue)
        existing_memories = await self.storage.get_memories(patient_id)

        proposals = []
        excluded_items = []
        clarifications_needed = []

        for cand in raw_candidates:
            cat = cand.get("category")
            fact_ar = cand.get("fact_ar", "").strip()

            if cat not in ALLOWED_CATEGORIES:
                excluded_items.append(f"Excluded category '{cat}': not in approved 8 domains.")
                continue

            # Prohibit diagnostic clinical labeling (Prompt 03 boundary)
            if any(term in fact_ar.lower() for term in FORBIDDEN_DIAGNOSES):
                excluded_items.append(f"Rejected candidate containing clinical diagnosis: {fact_ar}")
                continue

            # Prompt 04 Reconciliation
            action, matched_mem = self._reconcile_candidate(cand, existing_memories)

            schema_action = "ADD"
            if action == "CONFIRM":
                schema_action = "NO_ACTION"
            elif action == "FLAG_CONFLICT":
                schema_action = "UPDATE"
                clarifications_needed.append(f"تعارض محتمل بين: '{cand['fact_ar']}' و '{matched_mem['fact_ar']}'")

            proposal_entry = {
                "memory_type": cat,
                "content": fact_ar,
                "source_type": "patient_reported",
                "source_event_ids": [session_id],
                "supporting_evidence": cand.get("evidence", fact_ar),
                "confidence": cand.get("confidence", 0.9),
                "sensitivity": "standard",
                "time_sensitive": False,
                "proposed_action": schema_action,
                "requires_patient_confirmation": action == "FLAG_CONFLICT",
                "reason_for_retention": f"تحسين استمرارية المساندة النفسية في مجال {cat}",
            }
            proposals.append(proposal_entry)

            # Persist to storage if action is ADD or UPDATE
            if schema_action == "ADD":
                mem_id = f"mem_{uuid.uuid4().hex[:10]}"
                await self.storage.save_memory(
                    memory_id=mem_id,
                    patient_id=patient_id,
                    category=cat,
                    fact_ar=fact_ar,
                    confidence=cand.get("confidence", 0.9),
                    status="approved",
                )
            elif schema_action == "UPDATE" and matched_mem:
                conflict_id = f"mem_{uuid.uuid4().hex[:10]}"
                await self.storage.save_memory(
                    memory_id=conflict_id,
                    patient_id=patient_id,
                    category=cat,
                    fact_ar=f"[تحديث/استيضاح] {fact_ar}",
                    confidence=cand.get("confidence", 0.8),
                    status="conflict_flagged",
                )

        proposal_package = {
            "patient_id": patient_id,
            "session_id": session_id,
            "proposals": proposals,
            "excluded_items": excluded_items,
            "clarifications_needed": clarifications_needed,
        }

        # Validate proposal package against Section 13.1 schema
        jsonschema.validate(instance=proposal_package, schema=self._schema)

        return {
            "success": True,
            "patient_id": patient_id,
            "proposal_package": proposal_package,
            "memories_processed": proposals,
            "total_active_memories": len(await self.storage.get_memories(patient_id)),
        }

    def _extract_candidates_from_dialogue(self, dialogue: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Extracts structured facts across the 8 approved categories based on user turns.
        """
        candidates = []
        user_turns = [t["text"] for t in dialogue if t.get("role") in ("user", "patient")]

        for text in user_turns:
            # Coping preference detection
            if any(w in text for w in ["برتاح لما", "بحب أتنفس", "المشي بيهديني", "كوباية شاي"]):
                candidates.append({
                    "category": "coping_preference",
                    "fact_ar": f"يفضل تفريغ التوتر من خلال: {text.strip()}",
                    "confidence": 0.9,
                    "evidence": text.strip(),
                })
            # Patient goal detection
            elif any(w in text for w in ["نفسي", "هدفي", "عايز أنام كويس", "عايز أبطل تفكير"]):
                candidates.append({
                    "category": "patient_goal",
                    "fact_ar": f"يهدف إلى: {text.strip()}",
                    "confidence": 0.85,
                    "evidence": text.strip(),
                })
            # Personal history / background
            elif any(w in text for w in ["بشتغل", "مهندس", "طالب", "عايش في", "متجوز", "خريج"]):
                candidates.append({
                    "category": "personal_history",
                    "fact_ar": f"معلومات شخصية: {text.strip()}",
                    "confidence": 0.95,
                    "evidence": text.strip(),
                })
            # Symptom report
            elif any(w in text for w in ["بحس بضيق", "ضربات قلبي سريعة", "صداع", "أرق", "صاحي قلقان"]):
                candidates.append({
                    "category": "symptom_report",
                    "fact_ar": f"إفادة بأعراض توتر جسدي: {text.strip()}",
                    "confidence": 0.88,
                    "evidence": text.strip(),
                })
            # Generic meaningful statement if length > 15 chars and not already matched
            elif len(text.strip()) > 20 and not candidates:
                candidates.append({
                    "category": "coping_preference",
                    "fact_ar": f"شارك تفصيلاً: {text.strip()}",
                    "confidence": 0.75,
                    "evidence": text.strip(),
                })

        return candidates

    def _reconcile_candidate(
        self, candidate: Dict[str, Any], existing_memories: List[Dict[str, Any]]
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """Determines whether candidate matches, contradicts, or is novel (Prompt 04)."""
        cand_fact = candidate.get("fact_ar", "").strip()
        cand_cat = candidate.get("category")

        for mem in existing_memories:
            if mem.get("category") != cand_cat:
                continue

            existing_fact = mem.get("fact_ar", "").strip()

            # Exact or close match -> CONFIRM
            if cand_fact in existing_fact or existing_fact in cand_fact:
                return "CONFIRM", mem

            # Contradiction heuristic (e.g. "بحب" vs "مابحبش") -> FLAG_CONFLICT
            if ("بحب" in existing_fact and "مابحبش" in cand_fact) or (
                "مابحبش" in existing_fact and "بحب" in cand_fact
            ):
                return "FLAG_CONFLICT", mem

        return "ADD", None

    async def build_patient_session_context(self, patient_id: str) -> str:
        """
        Builds a compact, relevant context package for an upcoming live session
        conforming to Prompt 06 (Patient Context Builder) and Law 151/2020.
        """
        has_consent = await self.check_consent(patient_id)
        if not has_consent:
            return "سياق المريض: لا توجد ذاكرة مسبقة مصرح بها (لم تُمنح موافقة القانون 151 لسنة 2020 لحفظ الذاكرة الطولية)."

        memories = await self.storage.get_memories(patient_id)
        if not memories:
            return "سياق المريض: جلسة أولى جديدة، لا توجد سجلات سابقة للمريض."

        # Group by category according to Prompt 06
        goals = [m["fact_ar"] for m in memories if m.get("category") == "patient_goal"]
        coping = [m["fact_ar"] for m in memories if m.get("category") == "coping_preference"]
        history = [m["fact_ar"] for m in memories if m.get("category") in ("personal_history", "symptom_report")]
        conflicts = [m["fact_ar"] for m in memories if m.get("status") == "conflict_flagged"]

        lines = ["# سياق المريض المسبق المصرح به (Prompt 06 - Law 151/2020):"]
        if goals:
            lines.append("## أهداف المريض المصرح بها:")
            for g in goals:
                lines.append(f"- {g}")
        if coping:
            lines.append("## أساليب دعم وتفريغ يفضلها:")
            for c in coping:
                lines.append(f"- {c}")
        if history:
            lines.append("## معلومات وسياق شخصي سابق (تحتاج تأكيد رقيق إذا كانت قديمة):")
            for h in history:
                lines.append(f"- {h}")
        if conflicts:
            lines.append("## نقاط غير محسومة أو تحتاج استيضاح هادئ:")
            for cf in conflicts:
                lines.append(f"- {cf}")

        lines.append(
            "\nتوجيه لفضفضة: استخدم هذا السياق بلطف (مثل 'آخر مرة كنت بتقول...') ولا تفرضه إطلاقاً إذا رغب المريض في الحديث عن موضوع جديد تماماً."
        )
        return "\n".join(lines)

    async def get_patient_memories(self, patient_id: str) -> List[Dict[str, Any]]:
        return await self.storage.get_memories(patient_id)

    async def erase_memory(self, memory_id: str, patient_id: str) -> bool:
        """Right to Erasure under Law 151/2020."""
        return await self.storage.delete_memory(memory_id, patient_id)
