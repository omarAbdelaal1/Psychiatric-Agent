# Phase 1 Handoff Document: Clinical Knowledge & Safety Specifications

- **From Phase**: Phase 1 (Architecture, Clinical Knowledge & Safety Specifications)
- **To Phase**: Phase 2 (Data Privacy, Consent Governance & Memory Engine)
- **Tasks Completed**: Task 1.1 (Clinical Knowledge & Crisis Hotlines Catalog), Task 1.2 (System Prompt Catalog & Knowledge Service)
- **Active Specialist**: `roster/specialized/healthcare-customer-service.md` (`LOADED` → `VERIFIED` → `DORMANT`)

---

## 1. Deliverables Summary
- [`clinical_knowledge/protocols.json`](file:///c:/sharing1/ML4/psychiatric_agent/clinical_knowledge/protocols.json): 4 evidence-based clinician protocols (5-4-3-2-1, 4-4-4-4, CBT reframing, micro-activation).
- [`safety_policies/egyptian_crisis_directory.json`](file:///c:/sharing1/ML4/psychiatric_agent/safety_policies/egyptian_crisis_directory.json): 6 verified Egyptian emergency crisis contacts including 16328, 123, 08008880700, 0220816831, 16000, 15115.
- [`prompts/live_agent/system_prompt.md`](file:///c:/sharing1/ML4/psychiatric_agent/prompts/live_agent/system_prompt.md): Egyptian Colloquial Arabic companion system prompt (فضفضة).
- [`prompts/safety/safety_signal_analysis.md`](file:///c:/sharing1/ML4/psychiatric_agent/prompts/safety/safety_signal_analysis.md): Real-time safety risk analyzer prompt.
- [`prompts/memory/memory_extractor.md`](file:///c:/sharing1/ML4/psychiatric_agent/prompts/memory/memory_extractor.md): Law 151/2020 memory extraction prompt.
- [`prompts/reporting/patient_friendly_recap.md`](file:///c:/sharing1/ML4/psychiatric_agent/prompts/reporting/patient_friendly_recap.md): Arabic post-session recap prompt.
- [`backend/services/knowledge_service.py`](file:///c:/sharing1/ML4/psychiatric_agent/backend/services/knowledge_service.py): Python service for protocol matching, contraindication exclusion, and crisis keyword triage.

---

## 2. Agent Compliance Report
### Healthcare Customer Service (`roster/specialized/healthcare-customer-service.md`)
- ✅ **Applied: Never provide clinical advice or diagnose**: Explicitly encoded into `system_prompt.md` and `memory_extractor.md` prohibiting clinical diagnosis strings.
- ✅ **Applied: Immediate emergency diversion**: `detect_crisis_signal` stops standard advice and outputs the approved national crisis referral text with 16328 and 123.
- ✅ **Applied: Empathy before process**: The companion persona enforces single-question turns and emotional validation before suggesting coping exercises.
- ✅ **Avoided Anti-Pattern: Superficial or robotic counseling**: The Egyptian colloquial persona speaks unhurried, warm dialect Arabic ("أهلاً بيك، أنا معاك وسامعك بكل اهتمام").

---

## 3. Constraints & Invariants For Phase 2
- Phase 2 (`data-privacy-officer`) must enforce Egyptian Personal Data Protection Law No. 151/2020:
  1. No memory extraction or persistence unless explicit `long_term_memory` consent has been granted.
  2. Memory extraction must restrict candidate items strictly to the 8 approved categories.
  3. Support full Right to Erasure (`DELETE`).

---

## 4. Phase Gate Decision
- **Gate Status**: `✅ PASS`
- **Verification Evidence**: Python validation confirmed 4 loaded protocols, 6 crisis contacts, primary hotline 16328, and positive crisis keyword trigger.
