"""
Full-Duplex Bidirectional Live Audio Streaming Bridge for Fadfada Psychiatric Agent.
Directly connects browser client to Google Gemini Live API via BidiGenerateContent WebSocket.
Adopts the architecture from sales_voice_agent_demo while enforcing Egyptian psychiatric protocols.
"""

import asyncio
import base64
import json
import logging
import math
import struct
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from backend import config
from backend.services.knowledge_service import KnowledgeService
from backend.services.psychiatric_tools import (
    GEMINI_PSYCHIATRIC_TOOLS,
    execute_psychiatric_tool,
)

logger = logging.getLogger("fadfada.bridge")


def append_with_whitespace(existing: str, chunk: str) -> str:
    if not chunk:
        return existing
    if not existing:
        return chunk.strip()
    c = chunk
    if c in [",", ".", "!", "?", "،", "؟", ":", ";", "؛"]:
        return existing.rstrip() + c + " "
    if existing[-1] not in " \t\n\r" and c[0] not in " \t\n\r":
        return existing + " " + c
    return existing + c


def deduplicate_overlap_and_append(existing: str, chunk: str) -> str:
    """Appends chunk while deduplicating word-level overlap at chunk boundaries."""
    if not chunk:
        return existing
    if not existing:
        return chunk.strip()

    clean_chunk = chunk.strip()
    clean_existing = existing.strip()

    exist_words = clean_existing.split()
    chunk_words = clean_chunk.split()

    max_overlap = min(len(exist_words), len(chunk_words), 5)
    for n in range(max_overlap, 0, -1):
        if exist_words[-n:] == chunk_words[:n]:
            remaining_chunk = " ".join(chunk_words[n:])
            if not remaining_chunk:
                return existing
            return append_with_whitespace(existing, remaining_chunk)

    return append_with_whitespace(existing, chunk)


def generate_pcm24k_audio_frame(duration_ms: int = 100, freq: float = 220.0, volume: float = 0.3) -> bytes:
    """
    Generates a 24,000 Hz, 16-bit mono PCM audio chunk (duration_ms) with soft sinusoidal
    waveform and smooth envelope. Useful for audio testing and diagnostic signals.
    """
    sample_rate = config.AUDIO_OUTPUT_SAMPLE_RATE
    total_samples = int(sample_rate * (duration_ms / 1000.0))
    raw_bytes = bytearray()

    for i in range(total_samples):
        t = i / total_samples
        envelope = math.sin(math.pi * t)
        val = (
            math.sin(2 * math.pi * freq * (i / sample_rate)) * 0.7
            + math.sin(2 * math.pi * (freq * 1.5) * (i / sample_rate)) * 0.3
        )
        sample = int(val * volume * envelope * 32767.0)
        sample = max(-32768, min(32767, sample))
        raw_bytes.extend(struct.pack("<h", sample))

    return bytes(raw_bytes)


class GeminiLiveBridge:
    def __init__(
        self,
        session_id: str,
        patient_id: str,
        knowledge_service: KnowledgeService,
        send_to_client: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
        voice: str = "Aoede",
        patient_context: str = "",
    ):
        self.session_id = session_id
        self.patient_id = patient_id
        self.knowledge_service = knowledge_service
        self.send_to_client = send_to_client
        self.patient_context = patient_context
        # Strictly lock voice to single permanent Aoede voice
        self.voice = config.DEFAULT_VOICE
        self.audio_generation: int = 0

        self.gemini_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_reconnecting = False
        self.is_closed = False

        # Turn transcript tracking
        self.current_user_text = ""
        self.current_agent_text = ""

        # Load Egyptian Colloquial system prompt
        self.system_prompt_text = (
            "أنتِ 'فضفضة' (Fadfada) — رفيقة استماع داعمة ومريحة نفسياً تتحدثين دائماً بالعامية المصرية المعاصرة فقط.\n"
            "- تحدثي دائماً وحصرياً بالعامية المصرية الأصيلة ولا تستخدمي أي لغة أو لهجة أخرى حتى لو تحدث المستخدم بلغة أخرى.\n"
            "- الاستثناء الوحيد هو الكلمات والمصطلحات الإنجليزية الشائعة في الصحة النفسية التي يصعب ترجمتها (مثل Overthinking, Burnout, Panic attack, Trigger, Stress, Safe space, Trauma).\n"
            "- سؤال واحد فقط في كل مرة، وجمل قصيرة ودافئة.\n"
            "- لا تقدمي أي تشخيصات طبية ولا تصفي أي أدوية مطلقاً.\n"
            "- في حالات الخطر أو الانتحار، استخدمي أداة escalate_crisis وانصحي فوراً بالاتصال بالخط الساخن 16328 أو الإسعاف 123.\n"
            "- عند القلق المفرط أو تسارع الأنفاس، استخدمي أداة trigger_grounding_exercise لمشاركة تمرين التنفس المربع 4-4-4."
        )
        sys_prompt_file = config.BASE_DIR / "prompts" / "live_agent" / "system_prompt.md"
        if sys_prompt_file.exists():
            try:
                with open(sys_prompt_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self.system_prompt_text = content
            except Exception as e:
                logger.warning(f"Could not read system prompt file: {e}")

    async def connect_gemini(self) -> bool:
        """Establishes persistent bidirectional connection with Gemini Live API with automatic key rotation on quota."""
        api_keys = getattr(config, "GEMINI_API_KEYS", [config.GEMINI_API_KEY]) if config.GEMINI_API_KEY else []
        if not api_keys:
            logger.error("No GEMINI_API_KEY available. Cannot connect to Gemini Live.")
            return False

        if self.gemini_ws is not None:
            try:
                await self.gemini_ws.close()
            except Exception:
                pass
            self.gemini_ws = None

        logger.info(f"Connecting to Gemini Live API with model: {config.MODEL_LIVE}...")

        full_instruction = self.system_prompt_text
        if self.patient_context:
            full_instruction += f"\n\n---\n{self.patient_context}\n"

        setup_message = {
            "setup": {
                "model": f"models/{config.MODEL_LIVE}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": self.voice
                            }
                        }
                    }
                },
                "outputAudioTranscription": {},
                "systemInstruction": {
                    "parts": [{"text": full_instruction}]
                },
                "tools": [
                    {
                        "functionDeclarations": GEMINI_PSYCHIATRIC_TOOLS
                    }
                ]
            }
        }

        for candidate_key in api_keys:
            ws_url = (
                f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={candidate_key}"
            )
            try:
                new_ws = await websockets.connect(
                    ws_url,
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                )

                await new_ws.send(json.dumps(setup_message))
                setup_response_raw = await new_ws.recv()
                if isinstance(setup_response_raw, bytes):
                    setup_response_raw = setup_response_raw.decode("utf-8")
                setup_resp = json.loads(setup_response_raw)
                logger.info(f"Gemini setup response received with key {candidate_key[:12]}...: {setup_resp}")

                self.gemini_ws = new_ws
                self.is_connected = True
                self.is_reconnecting = False
                return True

            except Exception as e:
                logger.warning(f"Connection attempt with key {candidate_key[:12]}... failed: {e}")
                continue

        logger.error("All Gemini API keys exhausted or failed.")
        self.is_connected = False
        return False

    async def initialize(self) -> None:
        """Initializes connection to Gemini and notifies client."""
        connected = await self.connect_gemini()
        await self.send_to_client({
            "type": "ready",
            "session_id": self.session_id,
            "voice": self.voice,
            "connected": connected,
            "model": config.MODEL_LIVE,
            "audio_spec": {
                "input_sample_rate": config.AUDIO_INPUT_SAMPLE_RATE,
                "output_sample_rate": config.AUDIO_OUTPUT_SAMPLE_RATE,
                "channels": config.AUDIO_CHANNELS,
                "frame_ms": 100,
            },
        })

    async def handle_audio_chunk(self, pcm_base64: str) -> None:
        """Forwards 16kHz PCM audio chunk from client microphone directly to Gemini Live."""
        if not self.gemini_ws or not self.is_connected:
            return

        try:
            gemini_msg = {
                "realtimeInput": {
                    "audio": {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": pcm_base64
                    }
                }
            }
            await self.gemini_ws.send(json.dumps(gemini_msg))
        except Exception as e:
            logger.warning(f"Failed to forward audio chunk to Gemini: {e}")

    async def handle_turn_complete(self) -> None:
        """Finalize the current realtime audio input stream (not cancel generation)."""
        if not self.gemini_ws or not self.is_connected:
            return

        try:
            await self.gemini_ws.send(json.dumps({
                "realtimeInput": {
                    "audioStreamEnd": True
                }
            }))
        except Exception as e:
            logger.warning(f"Failed to end realtime audio input: {e}")

    async def handle_text_turn(self, user_text: str) -> None:
        """Sends user text to Gemini Live and runs crisis pre-check."""
        # 1. Immediate Crisis Pre-check on text
        crisis_check = self.knowledge_service.detect_crisis_signal(user_text)
        if crisis_check["is_crisis"]:
            await self.send_to_client({
                "type": "crisis_alert",
                "details": crisis_check,
                "primary_hotline": "16328",
                "ambulance": "123",
            })

        if not self.gemini_ws or not self.is_connected:
            return

        try:
            gemini_msg = {
                "clientContent": {
                    "turns": [
                        {
                            "role": "user",
                            "parts": [{"text": user_text}]
                        }
                    ],
                    "turnComplete": True
                }
            }
            await self.gemini_ws.send(json.dumps(gemini_msg))
        except Exception as e:
            logger.warning(f"Failed to send text turn to Gemini: {e}")

    async def handle_user_interrupt(self) -> None:
        """Explicitly cancels the currently generated response via documented Live API controls."""
        logger.info(f"Explicit user interrupt for session {self.session_id}")
        self.audio_generation += 1

        if self.gemini_ws and self.is_connected:
            try:
                # Documented Live API cancel signal: clientContent.turnComplete=True
                await self.gemini_ws.send(json.dumps({
                    "clientContent": {
                        "turnComplete": True
                    }
                }))
            except Exception as e:
                logger.warning(f"Failed to cancel Gemini generation: {e}")

        # Notify client to immediately silence speakers and advance generation ID
        await self.send_to_client({
            "type": "interrupted",
            "reason": "manual",
            "generation_id": self.audio_generation,
        })

    async def gemini_listen_loop(self, on_turn_complete_callback: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None) -> None:
        """Continuous loop reading responses from Gemini Live and streaming to client."""
        while not self.is_closed:
            if not self.gemini_ws or not self.is_connected:
                await asyncio.sleep(0.2)
                continue

            try:
                raw_response = await self.gemini_ws.recv()
            except ConnectionClosed:
                if self.is_closed:
                    break
                logger.info("Gemini Live connection closed. Attempting reconnect...")
                self.is_connected = False
                await asyncio.sleep(1.0)
                await self.connect_gemini()
                continue
            except Exception as e:
                if not self.is_closed:
                    logger.warning(f"Error receiving from Gemini: {e}")
                break

            try:
                if isinstance(raw_response, bytes):
                    raw_response = raw_response.decode("utf-8")

                resp_json = json.loads(raw_response)
                server_content = resp_json.get("serverContent")

                if server_content:
                    # 1. Process Interrupted first (Barge-in / cancel detected by Gemini)
                    # Advances generation ID immediately so any audio parts in this packet or in-flight are invalidated
                    if server_content.get("interrupted"):
                        self.audio_generation += 1
                        logger.info(f"Gemini Live reported generation interrupted (new generation_id: {self.audio_generation})")
                        interrupted_agent_text = self.current_agent_text.strip()
                        await self.send_to_client({
                            "type": "interrupted",
                            "reason": "server_generation_interrupted",
                            "generation_id": self.audio_generation,
                            "partial_text": interrupted_agent_text,
                        })

                    # 2. User transcription chunk (from Gemini's internal STT)
                    in_trans = server_content.get("inputTranscription") or resp_json.get("inputTranscription")
                    if in_trans and isinstance(in_trans, dict):
                        user_chunk = in_trans.get("text", "")
                        if user_chunk:
                            self.current_user_text = deduplicate_overlap_and_append(self.current_user_text, user_chunk)
                            await self.send_to_client({
                                "type": "user_transcription",
                                "text": user_chunk,
                                "generation_id": self.audio_generation,
                            })
                            # Real-time crisis detection on user spoken words
                            crisis_check = self.knowledge_service.detect_crisis_signal(user_chunk)
                            if crisis_check["is_crisis"]:
                                await self.send_to_client({
                                    "type": "crisis_alert",
                                    "details": crisis_check,
                                    "primary_hotline": "16328",
                                    "ambulance": "123",
                                    "generation_id": self.audio_generation,
                                })

                    # 3. Agent output transcription chunk (Canonical source for agent spoken text)
                    out_trans = server_content.get("outputTranscription") or resp_json.get("outputTranscription")
                    if out_trans and isinstance(out_trans, dict):
                        agent_chunk = out_trans.get("text", "")
                        if agent_chunk:
                            self.current_agent_text = deduplicate_overlap_and_append(self.current_agent_text, agent_chunk)
                            await self.send_to_client({
                                "type": "agent_text",
                                "text": agent_chunk,
                                "generation_id": self.audio_generation,
                            })

                    # 4. Model Audio Parts (24kHz PCM Little-Endian mono)
                    # Stale protection: discard audio parts if this turn was interrupted in this event
                    if not server_content.get("interrupted"):
                        model_turn = server_content.get("modelTurn")
                        if model_turn:
                            parts = model_turn.get("parts", [])
                            for part in parts:
                                if "inlineData" in part:
                                    audio_base64 = part["inlineData"].get("data")
                                    if audio_base64:
                                        await self.send_to_client({
                                            "type": "audio",
                                            "data": audio_base64,
                                            "generation_id": self.audio_generation,
                                        })

                    # 5. Turn / Generation Complete
                    if server_content.get("turnComplete") or server_content.get("generationComplete"):
                        user_final = self.current_user_text.strip()
                        agent_final = self.current_agent_text.strip()
                        if on_turn_complete_callback and (user_final or agent_final):
                            await on_turn_complete_callback(user_final, agent_final)

                        self.current_user_text = ""
                        self.current_agent_text = ""
                        await self.send_to_client({
                            "type": "turn_complete",
                            "generation_id": self.audio_generation,
                        })

                # 6. Tool / Function Calls
                tool_call = resp_json.get("toolCall") or (server_content.get("toolCall") if server_content else None)
                if tool_call:
                    function_calls = tool_call.get("functionCalls", [])
                    function_responses = []

                    for call in function_calls:
                        call_id = call.get("id")
                        call_name = call.get("name")
                        call_args = call.get("args", {})
                        logger.info(f"Gemini requested tool call: {call_name} with args: {call_args}")

                        # Execute tool
                        result = execute_psychiatric_tool(call_name, call_args)

                        # Broadcast UI event
                        if call_name == "trigger_grounding_exercise":
                            await self.send_to_client({
                                "type": "grounding_triggered",
                                "exercise": result.get("exercise"),
                                "title_ar": result.get("title_ar"),
                                "guidance_ar": result.get("guidance_ar"),
                            })
                        elif call_name == "escalate_crisis":
                            await self.send_to_client({
                                "type": "crisis_alert",
                                "urgency": result.get("urgency"),
                                "primary_hotline": result.get("primary_hotline", {}).get("number", "16328"),
                                "ambulance": "123",
                            })

                        function_responses.append({
                            "response": {"output": result},
                            "id": call_id,
                        })

                    # Send tool response back to Gemini
                    tool_resp_msg = {
                        "toolResponse": {
                            "functionResponses": function_responses
                        }
                    }
                    if self.gemini_ws and self.is_connected:
                        await self.gemini_ws.send(json.dumps(tool_resp_msg))
                        logger.info("Sent psychiatric toolResponse back to Gemini")

            except Exception as proc_err:
                logger.warning(f"Error handling Gemini Live response: {proc_err}", exc_info=True)

    async def close(self) -> None:
        """Closes the bridge gracefully."""
        self.is_closed = True
        self.is_connected = False
        if self.gemini_ws:
            try:
                await self.gemini_ws.close()
            except Exception:
                pass
            self.gemini_ws = None
