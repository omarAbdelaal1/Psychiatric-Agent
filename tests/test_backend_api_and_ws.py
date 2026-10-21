import json
import pytest
from fastapi.testclient import TestClient
from backend.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "fadfada-psychiatric-agent"
    assert data["audio_spec"]["uplink_pcm_sample_rate"] == 16000
    assert data["audio_spec"]["downlink_pcm_sample_rate"] == 24000


def test_system_info_endpoint(client):
    res = client.get("/api/info")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "FADFADA (فضفضة)"
    assert "16328" in data["primary_emergency_hotline"]["phone_number"]
    assert "151" in data["legal_governance"]


def test_protocols_endpoint(client):
    res = client.get("/api/protocols")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 4
    assert len(data["protocols"]) >= 4


def test_crisis_endpoint(client):
    res = client.get("/api/crisis")
    assert res.status_code == 200
    data = res.json()
    assert len(data["crisis_directory"]) >= 6
    assert data["primary"]["phone_number"] == "16328"


def test_patient_consent_and_profile_endpoint(client):
    patient_id = "test_rest_pat"

    # Set consent
    res_consent = client.post(f"/api/patient/{patient_id}/consent", json={"granted": True})
    assert res_consent.status_code == 200
    assert res_consent.json()["granted"] is True

    # Get profile
    res_profile = client.get(f"/api/patient/{patient_id}")
    assert res_profile.status_code == 200
    profile = res_profile.json()
    assert profile["patient_id"] == patient_id
    assert profile["consent"]["long_term_memory"] is True


def test_security_headers_compliance(client):
    res = client.get("/health")
    headers = res.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["x-xss-protection"] == "1; mode=block"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "microphone=(self)" in headers["permissions-policy"]


def test_websocket_live_handshake_and_stream(client):
    with client.websocket_connect("/ws/live") as ws:
        # 1. First frame: server ready handshake
        msg_ready = json.loads(ws.receive_text())
        assert msg_ready["type"] == "ready"
        assert msg_ready["audio_spec"]["input_sample_rate"] == 16000
        assert msg_ready["audio_spec"]["output_sample_rate"] == 24000

        # 2. Ping-pong roundtrip verification
        ws.send_text(json.dumps({"type": "ping"}))
        msg_pong = json.loads(ws.receive_text())
        assert msg_pong["type"] == "pong"

        # 3. User barge-in interrupt
        ws.send_text(json.dumps({"type": "user_interrupt"}))
        msg_int = json.loads(ws.receive_text())
        assert msg_int["type"] == "interrupted"

        # 4. Immediate Crisis signal test via text channel
        ws.send_text(json.dumps({"type": "text", "text": "مش قادر أعيش وعايز أنتحر"}))
        msg_crisis = json.loads(ws.receive_text())
        assert msg_crisis["type"] == "crisis_alert"
        assert msg_crisis["primary_hotline"] == "16328"
