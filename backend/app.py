"""
FastAPI Application & Live Streaming Gateway for Fadfada Psychiatric Agent.
Implements AppSec middleware, REST APIs, and full-duplex WebSocket gateway.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config
from backend.services.gemini_live_bridge import GeminiLiveBridge
from backend.services.knowledge_service import KnowledgeService
from backend.services.memory_service import MemoryService
from backend.services.report_service import ReportService
from backend.storage import SimpleStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fadfada.app")

# Initialize core services
storage = SimpleStorage(config.DATABASE_PATH)
knowledge_service = KnowledgeService()
memory_service = MemoryService(storage)
report_service = ReportService(storage)

app = FastAPI(
    title="FADFADA (فضفضة) AI Psychiatric Agent",
    description="Empathetic voice-first mental health companion in contemporary Egyptian Colloquial Arabic",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# AppSec Defense-in-Depth Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Allow iframe embeds within SAMEORIGIN for design-variants switcher
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    return response


# Static file mounts
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
VARIANTS_DIR = BASE_DIR / "design-variants"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

if VARIANTS_DIR.exists():
    app.mount("/design-variants-static", StaticFiles(directory=str(VARIANTS_DIR)), name="variants_static")


# Pydantic Schemas for Requests
class ConsentRequest(BaseModel):
    granted: bool


class ExtractMemoriesRequest(BaseModel):
    patient_id: str


class TextTurnRequest(BaseModel):
    session_id: str
    patient_id: str
    text: str


class NormalizeTranscriptRequest(BaseModel):
    text: str


class RecordTurnRequest(BaseModel):
    patient_id: str = "default_user"
    user_text: Optional[str] = ""
    agent_text: Optional[str] = ""


# ============================================================================
# REST Endpoints
# ============================================================================


@app.get("/")
async def root():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Fadfada Psychiatric Agent Gateway"}


@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "fadfada-psychiatric-agent",
        "version": "1.0.0",
        "models": {
            "live": config.MODEL_LIVE,
            "flash": config.MODEL_FLASH,
        },
        "audio_spec": {
            "uplink_pcm_sample_rate": config.AUDIO_INPUT_SAMPLE_RATE,
            "downlink_pcm_sample_rate": config.AUDIO_OUTPUT_SAMPLE_RATE,
        },
    }


@app.get("/api/info")
async def system_info():
    return {
        "name": "FADFADA (فضفضة)",
        "dialect": "Egyptian Colloquial Arabic (العامية المصرية)",
        "disclaimer_ar": "فضفضة هو رفيق ذكاء اصطناعي داعم للمساندة النفسية والتفريغ العاطفي، وليس بديلاً عن الطبيب النفسي البشري المؤهل أو الطوارئ الطبية.",
        "primary_emergency_hotline": knowledge_service.get_primary_hotline(),
        "legal_governance": "Egyptian Law No. 151 of 2020 on Personal Data Protection",
        "supported_voices": ["Aoede", "Puck", "Charon", "Kore", "Fenrir"],
    }


@app.get("/api/live-config")
async def get_live_config(patient_id: str = "default_user"):
    """
    Returns real-time session configuration for client-side direct Gemini Live
    streaming when running on serverless environments (e.g. Vercel) where incoming
    WebSockets are unsupported.
    """
    api_key = config.GEMINI_API_KEY
    if not api_key and getattr(config, "GEMINI_API_KEYS", None):
        api_key = config.GEMINI_API_KEYS[0]

    system_prompt = (
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
                    system_prompt = content
        except Exception:
            pass

    patient_context = await memory_service.build_patient_session_context(patient_id)
    if patient_context:
        system_prompt += f"\n\n---\n{patient_context}\n"

    from backend.services.psychiatric_tools import GEMINI_PSYCHIATRIC_TOOLS

    return {
        "status": "ok",
        "has_api_key": bool(api_key),
        "api_key": api_key,
        "model": config.MODEL_LIVE,
        "voice": config.DEFAULT_VOICE,
        "ws_url": (
            f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={api_key}"
            if api_key
            else ""
        ),
        "system_instruction": system_prompt,
        "tools": [
            {
                "functionDeclarations": GEMINI_PSYCHIATRIC_TOOLS
            }
        ],
        "environment": "vercel" if os.getenv("VERCEL") else "local",
    }


@app.post("/api/session/{session_id}/record-turn")
async def record_session_turn(session_id: str, payload: RecordTurnRequest):
    if payload.user_text:
        await storage.add_message(session_id, "user", payload.user_text)
    if payload.agent_text:
        await storage.add_message(session_id, "assistant", payload.agent_text)
    return {"status": "recorded", "session_id": session_id}


@app.get("/api/protocols")
async def list_protocols(category: Optional[str] = None):
    return {
        "protocols": knowledge_service.get_protocols(category),
        "count": len(knowledge_service.get_protocols(category)),
    }


@app.get("/api/crisis")
async def list_crisis_directory():
    return {
        "crisis_directory": knowledge_service.get_crisis_directory(),
        "primary": knowledge_service.get_primary_hotline(),
    }


@app.get("/api/patient/{patient_id}")
async def get_patient_profile(patient_id: str):
    has_consent = await memory_service.check_consent(patient_id)
    memories = await memory_service.get_patient_memories(patient_id)
    return {
        "patient_id": patient_id,
        "consent": {
            "long_term_memory": has_consent,
            "governing_law": "Law 151/2020",
        },
        "active_memories_count": len(memories),
        "memories": memories,
    }


@app.post("/api/patient/{patient_id}/consent")
async def set_patient_consent(patient_id: str, payload: ConsentRequest):
    result = await memory_service.record_consent(patient_id, payload.granted)
    return result


@app.get("/api/patient/{patient_id}/memories")
async def get_memories(patient_id: str):
    memories = await memory_service.get_patient_memories(patient_id)
    return {
        "patient_id": patient_id,
        "memories": memories,
        "count": len(memories),
    }


@app.delete("/api/patient/{patient_id}/memories/{memory_id}")
async def delete_patient_memory(patient_id: str, memory_id: str):
    success = await memory_service.erase_memory(memory_id, patient_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found or unauthorized.")
    return {
        "success": True,
        "action": "erased",
        "memory_id": memory_id,
        "patient_id": patient_id,
        "statutory_right": "Right to Erasure under Egyptian Law No. 151/2020",
    }


@app.post("/api/session/{session_id}/extract-memories")
async def extract_session_memories(session_id: str, payload: ExtractMemoriesRequest):
    """
    Extracts and reconciles patient candidate memories (Prompt 03 & Prompt 04).
    Validates output against schemas/patient_memory.schema.json.
    """
    result = await memory_service.extract_and_reconcile(
        patient_id=payload.patient_id,
        session_id=session_id,
    )
    return result


@app.get("/api/session/{session_id}/detailed-report")
@app.post("/api/session/{session_id}/detailed-report")
async def get_session_detailed_report(session_id: str, patient_id: Optional[str] = None):
    """
    Generates a structured clinical support report (Prompt 05).
    Validated strictly against schemas/session_report.schema.json.
    """
    report = await report_service.generate_detailed_session_report(session_id, patient_id)
    return report


@app.get("/api/session/{session_id}/recap")
@app.post("/api/session/{session_id}/recap")
async def generate_session_recap(session_id: str, patient_id: Optional[str] = None):
    """
    Generates a warm, patient-friendly session recap in Egyptian Arabic (Prompt 08).
    """
    recap = await report_service.generate_patient_recap(session_id, patient_id)
    return recap


@app.post("/api/session/{session_id}/evaluate")
async def evaluate_session(session_id: str):
    """
    Audits session quality and boundary compliance (Prompt 09).
    """
    messages = await storage.get_messages(session_id)
    dialogue = [{"role": m["role"], "text": m["text"]} for m in messages]
    report = await report_service.generate_detailed_session_report(session_id)
    evaluation = report_service.evaluate_session_quality(dialogue, report)
    return evaluation


@app.post("/api/transcript/normalize")
async def normalize_transcript(payload: NormalizeTranscriptRequest):
    """
    Normalizes Egyptian Arabic transcript while preserving dialect and marking uncertainty (Prompt 10).
    """
    return report_service.normalize_egyptian_transcript(payload.text)


# ============================================================================
# WebSocket Live Full-Duplex Gateway (/ws/live)
# ============================================================================


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"sess_{int(asyncio.get_event_loop().time() * 1000)}"
    patient_id = "default_user"
    logger.info(f"New WebSocket connection accepted on /ws/live (Session: {session_id})")

    bridge: Optional[GeminiLiveBridge] = None

    async def send_to_client(data: Dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(data))
        except Exception as e:
            logger.debug(f"Failed to send to client websocket: {e}")

    async def on_turn_complete(user_text: str, agent_text: str) -> None:
        try:
            if user_text:
                await storage.add_message(session_id, "user", user_text)
            if agent_text:
                await storage.add_message(session_id, "assistant", agent_text)
        except Exception as e:
            logger.warning(f"Error persisting turn message: {e}")

    async def client_to_gemini():
        nonlocal session_id, patient_id, bridge
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            msg_type = data.get("type")

            if msg_type == "init":
                # Voice is strictly locked to single Aoede voice across all sessions
                bridge.voice = config.DEFAULT_VOICE
                req_sess = data.get("session_id")
                if req_sess:
                    session_id = req_sess
                    bridge.session_id = session_id
                req_pat = data.get("patient_id")
                if req_pat:
                    patient_id = req_pat
                    bridge.patient_id = patient_id
                await storage.create_session(session_id, patient_id)

            elif msg_type == "audio":
                pcm_b64 = data.get("data", "")
                await bridge.handle_audio_chunk(pcm_b64)

            elif msg_type == "audio_turn_complete":
                await bridge.handle_turn_complete()

            elif msg_type == "text":
                user_text = data.get("text", "")
                try:
                    await storage.add_message(session_id, "user", user_text)
                except Exception as e:
                    logger.warning(f"Error persisting typed message: {e}")
                await bridge.handle_text_turn(user_text)

            elif msg_type == "user_interrupt":
                await bridge.handle_user_interrupt()

            elif msg_type == "playback_state":
                if bridge:
                    bridge.is_client_playing = bool(data.get("is_playing", False))

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    try:
        await storage.create_session(session_id, patient_id)

        # Build pre-session patient context conforming to Prompt 06 (Law 151/2020)
        patient_context = await memory_service.build_patient_session_context(patient_id)

        # Initialize bridge with dynamic context
        bridge = GeminiLiveBridge(
            session_id=session_id,
            patient_id=patient_id,
            knowledge_service=knowledge_service,
            send_to_client=send_to_client,
            patient_context=patient_context,
        )
        await bridge.initialize()

        # Run client reader and gemini reader concurrently
        c2g_task = asyncio.create_task(client_to_gemini())
        g2c_task = asyncio.create_task(bridge.gemini_listen_loop(on_turn_complete))

        done, pending = await asyncio.wait(
            [c2g_task, g2c_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        for task in done:
            if not task.cancelled():
                try:
                    task.result()
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as task_err:
                    logger.warning(f"Task ended with exception: {task_err}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error in session {session_id}: {e}", exc_info=True)
    finally:
        if bridge:
            try:
                await bridge.close()
            except Exception:
                pass
        try:
            await storage.end_session(session_id)
        except Exception:
            pass
