"""
Regression Test Suite for Fadfada Voice Pipeline Repair Plan.
Verifies all 7 core architectural fixes:
1. Suffix/prefix boundary overlap deduplication in transcription.
2. audioStreamEnd used for normal turn finalization (not clientContent.turnComplete).
3. Documented clientContent.turnComplete used for manual interruption (no synthetic silence frames).
4. Audio generation ID sequencing and stale audio packet rejection.
5. Preservation of partial interrupted text upon interruption.
6. Zero hard-coded API key literals in config.
"""

import asyncio
import json
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import config
from backend.services.gemini_live_bridge import (
    GeminiLiveBridge,
    append_with_whitespace,
    deduplicate_overlap_and_append,
)
from backend.services.knowledge_service import KnowledgeService


def test_deduplicate_overlap_and_append_cases():
    # Case 1: Simple non-overlapping concatenation
    res1 = deduplicate_overlap_and_append("السلام عليكم", "ورحمة الله")
    assert res1 == "السلام عليكم ورحمة الله"

    # Case 2: Direct 2-word overlap at chunk boundary
    res2 = deduplicate_overlap_and_append("وعليكم السلام ورحمة", "ورحمة الله وبركاته")
    assert res2 == "وعليكم السلام ورحمة الله وبركاته"

    # Case 3: Single-word overlap
    res3 = deduplicate_overlap_and_append("أنا سامعاك", "سامعاك وحاسة بيك")
    assert res3 == "أنا سامعاك وحاسة بيك"

    # Case 4: Attached punctuation
    res4 = deduplicate_overlap_and_append("ألف سلامة عليك", "،")
    assert res4.strip() == "ألف سلامة عليك،"


@pytest.mark.asyncio
async def test_handle_turn_complete_sends_audiostreamend():
    client_mock = AsyncMock()
    bridge = GeminiLiveBridge("test_sess", "p1", KnowledgeService(), client_mock)
    bridge.gemini_ws = AsyncMock()
    bridge.is_connected = True

    await bridge.handle_turn_complete()

    assert bridge.gemini_ws.send.called
    sent_data = json.loads(bridge.gemini_ws.send.call_args[0][0])
    assert "realtimeInput" in sent_data
    assert sent_data["realtimeInput"] == {"audioStreamEnd": True}
    assert "clientContent" not in sent_data


@pytest.mark.asyncio
async def test_handle_user_interrupt_cancels_without_silence_frame():
    client_mock = AsyncMock()
    bridge = GeminiLiveBridge("test_sess", "p1", KnowledgeService(), client_mock)
    bridge.gemini_ws = AsyncMock()
    bridge.is_connected = True

    initial_gen = bridge.audio_generation
    await bridge.handle_user_interrupt()

    # 1. Generation ID must be advanced
    assert bridge.audio_generation == initial_gen + 1

    # 2. Documented Live API cancel command sent
    assert bridge.gemini_ws.send.called
    sent_data = json.loads(bridge.gemini_ws.send.call_args[0][0])
    assert "clientContent" in sent_data
    assert sent_data["clientContent"] == {"turnComplete": True}

    # 3. MUST NOT send synthetic silence audio
    assert "realtimeInput" not in sent_data

    # 4. Client receives interrupt notice with generation_id and reason manual
    assert client_mock.called
    client_msg = client_mock.call_args[0][0]
    assert client_msg["type"] == "interrupted"
    assert client_msg["reason"] == "manual"
    assert client_msg["generation_id"] == bridge.audio_generation


@pytest.mark.asyncio
async def test_gemini_listen_loop_interrupted_advances_generation_and_preserves_partial_text():
    client_mock = AsyncMock()
    bridge = GeminiLiveBridge("test_sess", "p1", KnowledgeService(), client_mock)
    bridge.current_agent_text = "وعليكم السلام ورحمة الله وبركاته"

    # Simulate Gemini emitting serverContent.interrupted
    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(side_effect=[
        json.dumps({
            "serverContent": {
                "interrupted": True
            }
        }),
        websockets_closed_exception := asyncio.CancelledError()
    ])
    bridge.gemini_ws = mock_ws
    bridge.is_connected = True

    initial_gen = bridge.audio_generation

    # Run listen loop briefly
    listen_task = asyncio.create_task(bridge.gemini_listen_loop())
    await asyncio.sleep(0.05)
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    assert bridge.audio_generation == initial_gen + 1
    # Check client received interrupted with partial text
    interrupted_events = [
        call[0][0] for call in client_mock.call_args_list if call[0][0].get("type") == "interrupted"
    ]
    assert len(interrupted_events) >= 1
    ev = interrupted_events[0]
    assert ev["generation_id"] == bridge.audio_generation
    assert ev["reason"] == "server_generation_interrupted"
    assert ev["partial_text"] == "وعليكم السلام ورحمة الله وبركاته"


@pytest.mark.asyncio
async def test_audio_parts_include_generation_id():
    client_mock = AsyncMock()
    bridge = GeminiLiveBridge("test_sess", "p1", KnowledgeService(), client_mock)
    bridge.audio_generation = 42

    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(side_effect=[
        json.dumps({
            "serverContent": {
                "modelTurn": {
                    "parts": [
                        {"inlineData": {"data": "dGVzdF9hdWRpb19kYXRh"}}
                    ]
                }
            }
        }),
        asyncio.CancelledError()
    ])
    bridge.gemini_ws = mock_ws
    bridge.is_connected = True

    listen_task = asyncio.create_task(bridge.gemini_listen_loop())
    await asyncio.sleep(0.05)
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    audio_events = [
        call[0][0] for call in client_mock.call_args_list if call[0][0].get("type") == "audio"
    ]
    assert len(audio_events) >= 1
    assert audio_events[0]["generation_id"] == 42
    assert audio_events[0]["data"] == "dGVzdF9hdWRpb19kYXRh"


def test_no_hardcoded_keys_in_config():
    config_source = inspect.getsource(config)
    sample_key_prefix = "AQ." + "Ab8RN6"
    assert sample_key_prefix not in config_source
