"""
Knowledge and Crisis Service for Fadfada Psychiatric Agent.
Indexes clinician-reviewed protocols and official Egyptian emergency directories.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fadfada.knowledge")


class KnowledgeService:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            # Root directory of psychiatric_agent
            self.base_dir = Path(__file__).resolve().parent.parent.parent
        else:
            self.base_dir = Path(base_dir)

        self.protocols_path = self.base_dir / "clinical_knowledge" / "protocols.json"
        self.crisis_path = self.base_dir / "safety_policies" / "egyptian_crisis_directory.json"

        self._protocols: List[Dict[str, Any]] = []
        self._crisis_directory: List[Dict[str, Any]] = []
        self.reload()

    def reload(self) -> None:
        """Loads or reloads protocols and crisis hotlines from disk."""
        if self.protocols_path.exists():
            with open(self.protocols_path, "r", encoding="utf-8") as f:
                self._protocols = json.load(f)
        else:
            self._protocols = []
            logger.warning(f"Protocols file not found at {self.protocols_path}")

        if self.crisis_path.exists():
            with open(self.crisis_path, "r", encoding="utf-8") as f:
                self._crisis_directory = json.load(f)
        else:
            self._crisis_directory = []
            logger.warning(f"Crisis directory not found at {self.crisis_path}")

    def get_protocols(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all clinical protocols, optionally filtered by category."""
        if category:
            return [p for p in self._protocols if p.get("category") == category]
        return list(self._protocols)

    def get_protocol_by_id(self, protocol_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific protocol by unique ID."""
        for p in self._protocols:
            if p.get("id") == protocol_id:
                return p
        return None

    def match_protocols(
        self,
        symptoms: List[str],
        exclude_contraindications: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Matches relevant protocols based on symptoms, strictly filtering out
        any with active contraindications.
        """
        contraindications = set(exclude_contraindications or [])
        symptom_set = set(symptoms)
        matched = []

        for proto in self._protocols:
            proto_contras = set(proto.get("contraindications", []))
            # If any contraindication is present, reject protocol
            if proto_contras.intersection(contraindications):
                continue

            proto_indications = set(proto.get("indications", []))
            overlap = proto_indications.intersection(symptom_set)
            if overlap:
                matched.append({
                    "protocol": proto,
                    "matched_indications": list(overlap),
                    "score": len(overlap)
                })

        # Sort by relevance score descending
        matched.sort(key=lambda x: x["score"], reverse=True)
        return [m["protocol"] for m in matched]

    def get_crisis_directory(self) -> List[Dict[str, Any]]:
        """Returns the full Egyptian crisis hotline directory."""
        return list(self._crisis_directory)

    def get_primary_hotline(self) -> Dict[str, Any]:
        """Returns the primary national psychiatric emergency hotline."""
        for contact in self._crisis_directory:
            if contact.get("is_primary"):
                return contact
        # Fallback to Egyptian MOH Mental Health Hotline
        return {
            "organization": "الأمانة العامة للصحة النفسية (وزارة الصحة)",
            "phone_number": "16328",
            "display_number": "16328",
            "availability": "24/7 مجاناً"
        }

    def select_therapeutic_protocol(
        self,
        current_need: str,
        symptoms: Optional[List[str]] = None,
        exclude_contraindications: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Selects an approved protocol from the clinician-reviewed therapeutic knowledge base
        conforming to Prompt 07 (Therapeutic Protocol Selector).
        """
        symptoms_list = symptoms or []
        need_lower = current_need.lower()

        # Extract symptomatic keywords if symptoms_list is empty
        if not symptoms_list:
            if any(k in need_lower for k in ["تنفس", "ضربات قلب", "نهجان", "خنقة", "صدر", "مش عارف اتنفس"]):
                symptoms_list.append("chest_tightness_emotional")
                symptoms_list.append("hyperventilation_rumination")
                symptoms_list.append("bodily_tension")
            if any(k in need_lower for k in ["قلق", "توتر", "بانيك", "panic", "خوف", "فزع"]):
                symptoms_list.append("acute_anxiety")
                symptoms_list.append("panic_feelings")
            if any(k in need_lower for k in ["تفكير", "overthinking", "دماغي مش راضية تقف", "فحص الأفكار"]):
                symptoms_list.append("catastrophizing")
                symptoms_list.append("all_or_nothing_thinking")

        matched = self.match_protocols(symptoms_list, exclude_contraindications)
        if not matched:
            return {
                "status": "NO_SUITABLE_PROTOCOL",
                "selected_protocol_id": "NO_SUITABLE_PROTOCOL",
                "protocol_id": "NO_SUITABLE_PROTOCOL",
                "protocol_name": "لا يوجد بروتوكول مطابق",
                "rationale": "No approved clinician-reviewed protocol matching the indicated need without active contraindications.",
                "conversational_adaptation_ar": "استمع للمريض باهتمام هادئ وشجعه يواصل الفضفضة براحته دون فرض أي تمرين.",
                "steps": [],
            }

        selected = matched[0]
        title = selected.get("title_ar") or selected.get("name_ar", "تمرين داعم")
        steps = selected.get("steps_ar", selected.get("steps", []))
        return {
            "status": "SELECTED",
            "selected_protocol_id": selected["id"],
            "protocol_id": selected["id"],
            "protocol_name": title,
            "category": selected.get("category", "general"),
            "steps": steps,
            "rationale": f"Protocol {selected['id']} is indicated for {', '.join(symptoms_list)} with zero active contraindications.",
            "conversational_adaptation_ar": (
                f"اقترح بهدوء وبصيغة استئذان: 'تحب نجرب سوا {title}؟ تمرين بسيط بياخد دقيقة وهيساعدك تهدي ضربات قلبك.' "
                "إذا وافق المريض، ابدأ معاه الخطوات واحدة واحدة، وإذا فضل يكمل كلام احترم رغبته فوراً."
            ),
            "protocol_details": selected,
        }

    def detect_crisis_signal(self, text: str) -> Dict[str, Any]:
        """
        Scans Egyptian Arabic text for explicit crisis triggers and suicidal ideation
        conforming to Prompt 02 (Safety Signal Analysis) and schemas/safety_signal.schema.json.
        """
        crisis_keywords = [
            "مش عايز أعيش",
            "مش عاوزه أعيش",
            "عايز أموت",
            "عايزه أموت",
            "أنتحر",
            "الانتحار",
            "أنهي حياتي",
            "أذيت نفسي",
            "عايز أخلص من الدنيا",
            "مش طايق أعيش",
            "أموت نفسي",
            "أقطع شراييني",
            "أرمي نفسي"
        ]

        acute_distress_keywords = [
            "بانيك أتاك",
            "نوبة هلع",
            "مش قادر أتنفس",
            "قلبي هيقف من الخوف",
            "حاسس إني بتخنق"
        ]

        text_lower = text.lower()
        suicide_detected = [kw for kw in crisis_keywords if kw in text_lower]
        distress_detected = [kw for kw in acute_distress_keywords if kw in text_lower]

        if suicide_detected:
            return {
                "is_crisis": True,
                "risk_level": "CRITICAL",
                "signal_categories": ["suicide_risk", "self_harm_concern"],
                "supporting_evidence": [
                    {
                        "evidence_type": "direct_patient_statement",
                        "quote_or_description": f"Spoken phrase contains: {', '.join(suicide_detected)}"
                    }
                ],
                "confidence": 0.98,
                "recommended_action": "escalate_immediate_crisis",
                "emergency_action": True,
                "suggested_hotlines": ["16328", "123"],
                "reasoning_ar": "تم رصد عبارات صريحة تشير للرغبة في الموت أو إيذاء النفس.",
                "matched_keywords": suicide_detected,
                "hotlines": self.get_crisis_directory(),
                "recommended_response_ar": (
                    "سلامتك وحياتك هي أهم حاجة دلوقتي. أنا صديق ذكاء اصطناعي ومش بديل عن الدعم البشري المتخصص في اللحظات الصعبة دي. "
                    "أرجوك اتصل فوراً بالخط الساخن للصحة النفسية على رقم 16328 أو اطلب الإسعاف 123، "
                    "أو اتواصل مع حد قريب منك تثق فيه يكون جنبك دلوقتي."
                )
            }

        if distress_detected:
            return {
                "is_crisis": False,
                "risk_level": "ACUTE_DISTRESS",
                "signal_categories": ["acute_distress"],
                "supporting_evidence": [
                    {
                        "evidence_type": "direct_patient_statement",
                        "quote_or_description": f"Spoken phrase contains: {', '.join(distress_detected)}"
                    }
                ],
                "confidence": 0.85,
                "recommended_action": "provide_hotline_resources",
                "emergency_action": False,
                "suggested_hotlines": ["16328"],
                "reasoning_ar": "رصد أعراض هلع أو ضيق تنفس حاد دون إشارات انتحار صريحة.",
                "matched_keywords": distress_detected,
                "hotlines": self.get_crisis_directory(),
            }

        return {
            "is_crisis": False,
            "risk_level": "LOW",
            "signal_categories": ["none"],
            "supporting_evidence": [],
            "confidence": 0.95,
            "recommended_action": "continue_support",
            "emergency_action": False,
            "suggested_hotlines": [],
            "reasoning_ar": "لا توجد إشارات خطر أو أزمة عاجلة في الإفادة الحالية.",
            "matched_keywords": []
        }
