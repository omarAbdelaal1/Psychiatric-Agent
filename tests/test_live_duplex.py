"""
Live Duplex Integration Test for Fadfada Psychiatric Agent with Google Gemini Live API.
Verifies the end-to-end connection, setup message, and audio/text roundtrip.
"""

import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets
from backend import config
from backend.services.gemini_live_bridge import generate_pcm24k_audio_frame

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_live_duplex")


async def run_live_duplex_verification():
    logger.info("==================================================")
    logger.info("Starting Gemini Live End-to-End Duplex Verification")
    logger.info(f"Target Model: {config.MODEL_LIVE}")
    logger.info(f"WS URL: {config.GEMINI_WS_URL[:70]}...")
    logger.info("==================================================")

    if not config.GEMINI_API_KEY:
        logger.error("FAIL: GEMINI_API_KEY is missing!")
        return False

    try:
        ws = await websockets.connect(
            config.GEMINI_WS_URL,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        )
        logger.info("Connected to Gemini BidiGenerateContent WebSocket!")

        # 1. Send Setup Message
        setup_msg = {
            "setup": {
                "model": f"models/{config.MODEL_LIVE}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": "Aoede"
                            }
                        }
                    }
                },
                "outputAudioTranscription": {},
                "systemInstruction": {
                    "parts": [{"text": "أنت فضفضة — رفيق استماع داعم ومريح نفسياً بالعامية المصرية. رد بكلمات قصيرة دافئة."}]
                }
            }
        }
        await ws.send(json.dumps(setup_msg))
        setup_resp_raw = await ws.recv()
        setup_resp = json.loads(setup_resp_raw)
        logger.info(f"Setup Handshake Response: {setup_resp}")
        assert "setupComplete" in setup_resp, f"Expected setupComplete, got: {setup_resp}"
        logger.info("SUCCESS: Setup complete verified!")

        # 2. Send User Conversational Turn (Egyptian Arabic)
        user_turn_msg = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": "مساء الخير يا فضفضة.. حاسس بضغط وتوتر من الشغل النهارده"}]
                    }
                ],
                "turnComplete": True
            }
        }
        await ws.send(json.dumps(user_turn_msg))
        logger.info("Sent user message to Gemini Live. Waiting for audio & transcription...")

        received_audio_bytes = 0
        received_text_chunks = []
        turn_completed = False

        for i in range(80):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
            except asyncio.TimeoutError:
                logger.info("Recv timeout reached. Concluding drain.")
                break
            data = json.loads(raw)
            logger.info(f"Frame {i} keys: {list(data.keys())}, serverContent keys: {list(data.get('serverContent', {}).keys())}")
            server_content = data.get("serverContent", {})
            if server_content.get("turnComplete") or server_content.get("generationComplete"):
                turn_completed = True
                logger.info(f"Gemini signaled turnComplete/generationComplete: True (frame {i})")
                break
            server_content = data.get("serverContent")
            if not server_content:
                continue

            # Model audio
            model_turn = server_content.get("modelTurn")
            if model_turn:
                for part in model_turn.get("parts", []):
                    if "inlineData" in part:
                        audio_b64 = part["inlineData"].get("data", "")
                        if audio_b64:
                            received_audio_bytes += len(base64.b64decode(audio_b64))
                    if "text" in part:
                        received_text_chunks.append(part.get("text", ""))

            # Transcription
            out_trans = server_content.get("outputTranscription")
            if out_trans and isinstance(out_trans, dict):
                t = out_trans.get("text")
                if t:
                    received_text_chunks.append(t)

            if server_content.get("turnComplete"):
                turn_completed = True
                logger.info("Gemini signaled turnComplete: True")
                break

        await ws.close()

        full_text = " ".join(received_text_chunks)
        logger.info(f"Received total audio bytes: {received_audio_bytes} bytes (~{received_audio_bytes / 48000:.2f} seconds of 24kHz audio)")
        logger.info(f"Spoken text from Fadfada: \"{full_text}\"")

        assert received_audio_bytes > 0, "No audio bytes received from Gemini Live!"
        assert turn_completed, "Turn complete signal not received!"
        logger.info("==================================================")
        logger.info("ALL VERIFICATIONS PASSED: Gemini Live duplex audio streaming is fully functional!")
        logger.info("==================================================")
        return True

    except Exception as e:
        logger.error(f"Live duplex verification error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(run_live_duplex_verification())
    sys.exit(0 if success else 1)
