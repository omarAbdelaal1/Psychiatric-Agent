import pytest
from backend.services.knowledge_service import KnowledgeService


@pytest.fixture
def knowledge_service():
    return KnowledgeService()


def test_protocols_loaded(knowledge_service):
    protocols = knowledge_service.get_protocols()
    assert len(protocols) >= 4
    categories = {p["category"] for p in protocols}
    assert "grounding" in categories
    assert "breathwork" in categories
    assert "cbt" in categories
    assert "behavioral_activation" in categories


def test_protocol_by_id(knowledge_service):
    proto = knowledge_service.get_protocol_by_id("box_breathing")
    assert proto is not None
    assert proto["title_ar"] == "تمرين التنفس المربع 4-4-4-4"
    assert len(proto["steps_ar"]) == 4


def test_symptom_matching_with_contraindication_filter(knowledge_service):
    # Match acute anxiety
    matched = knowledge_service.match_protocols(
        symptoms=["acute_anxiety"],
        exclude_contraindications=["active_suicidal_crisis"]
    )
    # Grounding 5-4-3-2-1 has contraindication 'active_suicidal_crisis', so it must be excluded!
    proto_ids = [p["id"] for p in matched]
    assert "grounding_54321" not in proto_ids

    # Match bodily tension with no contraindications
    matched_clean = knowledge_service.match_protocols(
        symptoms=["bodily_tension"],
        exclude_contraindications=[]
    )
    proto_ids_clean = [p["id"] for p in matched_clean]
    assert "box_breathing" in proto_ids_clean


def test_crisis_directory_completeness(knowledge_service):
    directory = knowledge_service.get_crisis_directory()
    assert len(directory) >= 6
    phone_numbers = [c["phone_number"] for c in directory]
    assert "16328" in phone_numbers
    assert "123" in phone_numbers
    assert "08008880700" in phone_numbers


def test_primary_hotline(knowledge_service):
    primary = knowledge_service.get_primary_hotline()
    assert primary["phone_number"] == "16328"
    assert "الأمانة العامة للصحة النفسية" in primary["organization"]


def test_crisis_signal_detection(knowledge_service):
    res_danger = knowledge_service.detect_crisis_signal("أنا تعبان جداً ومش عايز أعيش خلاص")
    assert res_danger["is_crisis"] is True
    assert res_danger["risk_level"] == "CRITICAL"
    assert "16328" in res_danger["recommended_response_ar"]

    res_safe = knowledge_service.detect_crisis_signal("أهلاً، حاسس بضغط شغل بس كويس الحمد لله")
    assert res_safe["is_crisis"] is False
    assert res_safe["risk_level"] == "LOW"
