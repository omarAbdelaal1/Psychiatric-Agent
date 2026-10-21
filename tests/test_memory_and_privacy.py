import pytest
from backend.services.memory_service import MemoryService
from backend.storage import SimpleStorage


@pytest.fixture
def memory_env(tmp_path):
    db_file = tmp_path / "test_memory.db"
    storage = SimpleStorage(db_file)
    service = MemoryService(storage)
    return storage, service


@pytest.mark.asyncio
async def test_law_151_consent_refusal(memory_env):
    storage, service = memory_env
    patient_id = "pat_law151_refuse"

    # User has not granted consent
    result = await service.extract_and_reconcile(
        patient_id=patient_id,
        session_id="sess_001",
        dialogue=[{"role": "user", "text": "أنا بشتغل مهندس وبحب المشي"}]
    )

    assert result["success"] is False
    assert result["reason"] == "CONSENT_WITHHELD"
    assert "151" in result["message_ar"]

    # Verify 0 memories saved in database
    memories = await storage.get_memories(patient_id)
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_consent_granting_and_extraction(memory_env):
    storage, service = memory_env
    patient_id = "pat_law151_allow"

    # Record consent
    consent_res = await service.record_consent(patient_id, True)
    assert consent_res["granted"] is True
    assert await service.check_consent(patient_id) is True

    # Extract memories from dialogue
    dialogue = [
        {"role": "user", "text": "أنا بشتغل مهندس برمجيات في المعادي"},
        {"role": "user", "text": "برتاح لما أعمل تمرين التنفس في البلكونة"}
    ]
    result = await service.extract_and_reconcile(
        patient_id=patient_id,
        session_id="sess_002",
        dialogue=dialogue
    )

    assert result["success"] is True
    assert len(result["memories_processed"]) >= 2

    # Verify memories in database
    memories = await service.get_patient_memories(patient_id)
    assert len(memories) >= 2
    categories = {m["category"] for m in memories}
    assert "personal_history" in categories
    assert "coping_preference" in categories


@pytest.mark.asyncio
async def test_prohibition_of_clinical_diagnoses(memory_env):
    storage, service = memory_env
    patient_id = "pat_no_diag"
    await service.record_consent(patient_id, True)

    # Simulated candidate dialogue containing prohibited diagnostic terms
    dialogue = [
        {"role": "user", "text": "الدكتور قال عندي اضطراب ثنائي القطب وعايز أتابعه"},
    ]
    result = await service.extract_and_reconcile(
        patient_id=patient_id,
        session_id="sess_diag",
        dialogue=dialogue
    )

    # Any extracted memory with forbidden diagnosis must be discarded
    memories = await service.get_patient_memories(patient_id)
    for m in memories:
        assert "اضطراب ثنائي القطب" not in m["fact_ar"]


@pytest.mark.asyncio
async def test_right_to_erasure(memory_env):
    storage, service = memory_env
    patient_id = "pat_erasure"
    await service.record_consent(patient_id, True)

    await service.extract_and_reconcile(
        patient_id=patient_id,
        session_id="sess_erase",
        dialogue=[{"role": "user", "text": "برتاح لما أمشي على النيل"}]
    )

    memories_before = await service.get_patient_memories(patient_id)
    assert len(memories_before) > 0
    mem_id = memories_before[0]["id"]

    # Execute Right to Erasure
    deleted = await service.erase_memory(mem_id, patient_id)
    assert deleted is True

    memories_after = await service.get_patient_memories(patient_id)
    assert len(memories_after) == 0
