"""
Clinical Function Calling Declarations & Execution for Fadfada Psychiatric Agent.
Provides Gemini Live with tools for grounding exercises and crisis escalation.
"""

from typing import Any, Dict, List

GEMINI_PSYCHIATRIC_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "trigger_grounding_exercise",
        "description": "Triggers a visual and structured clinical grounding exercise (Square Breathing 4-4-4 or 5-4-3-2-1 Sensory Grounding) on the user's screen when they experience acute anxiety, panic, or racing thoughts.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "exercise_name": {
                    "type": "STRING",
                    "description": "The specific grounding exercise to trigger: 'square_breathing' (التنفس المربع 4-4-4) or 'sensory_54321' (تمرين الحواس الخمس 5-4-3-2-1).",
                    "enum": ["square_breathing", "sensory_54321"]
                },
                "guidance_ar": {
                    "type": "STRING",
                    "description": "Gentle, brief verbal instruction in Egyptian Colloquial Arabic explaining the current step to the user."
                }
            },
            "required": ["exercise_name", "guidance_ar"]
        }
    },
    {
        "name": "escalate_crisis",
        "description": "Immediately escalates an acute psychiatric emergency, triggering emergency UI banners and guiding the user to Egyptian emergency hotlines (16328 for Mental Health, 123 for Ambulance). MUST be called if the user mentions suicidal ideation, self-harm, or severe danger.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "urgency_level": {
                    "type": "STRING",
                    "description": "Level of urgency: 'immediate' (life threat / self-harm) or 'high' (severe acute distress).",
                    "enum": ["immediate", "high"]
                },
                "reason": {
                    "type": "STRING",
                    "description": "Brief clinical reason for escalation."
                }
            },
            "required": ["urgency_level", "reason"]
        }
    },
    {
        "name": "select_therapeutic_protocol",
        "description": "Consults the clinician-reviewed therapeutic knowledge base to select an approved coping or grounding technique based on patient need conforming to Prompt 07.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "current_need": {
                    "type": "STRING",
                    "description": "Patient's current stated concern or emotional state (e.g. 'anxiety', 'racing_heart', 'overthinking')."
                }
            },
            "required": ["current_need"]
        }
    }
]


def execute_psychiatric_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Executes clinical tools called by Gemini Live and returns response payload."""
    if name == "trigger_grounding_exercise":
        exercise = args.get("exercise_name", "square_breathing")
        guidance = args.get("guidance_ar", "خد نفس هادي وعميق..")
        return {
            "status": "success",
            "exercise": exercise,
            "title_ar": "التنفس المربع (4-4-4)" if exercise == "square_breathing" else "تمرين الحواس الخمس (5-4-3-2-1)",
            "guidance_ar": guidance,
            "instruction": "Explain the step calmly in one gentle sentence in Egyptian Arabic and invite the user to breathe or observe."
        }

    elif name == "escalate_crisis":
        urgency = args.get("urgency_level", "immediate")
        reason = args.get("reason", "Crisis indicator detected")
        return {
            "status": "escalated",
            "urgency": urgency,
            "primary_hotline": {
                "name": "الخط الساخن للأمانة العامة للصحة النفسية وعلاج الإدمان (MOHP)",
                "number": "16328",
                "availability": "24/7 مجاناً"
            },
            "ambulance": "123",
            "instruction": "Urge the patient warmly to contact 16328 or 123 immediately and assure them that their life and safety are the top priority."
        }

    elif name == "select_therapeutic_protocol":
        from backend.services.knowledge_service import KnowledgeService
        ks = KnowledgeService()
        current_need = args.get("current_need", "")
        return ks.select_therapeutic_protocol(current_need=current_need)

    return {"status": "unrecognized_tool", "name": name}
