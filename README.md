# FADFADA (فضفضة) — Voice-First AI Psychiatric Companion

An empathetic, voice-first mental health support companion delivering psychiatrist-inspired conversations in natural Egyptian Colloquial Arabic (`العامية المصرية`).

Powered by Google's **Gemini Live API** (`gemini-3.8-live`) for bidirectional low-latency audio streaming, and **Gemini Flash** (`gemini-3.8-flash`) for real-time safety triage, memory extraction, and clinical reporting.

---

## 🌟 Key Features

1. **Natural Egyptian Arabic Voice Companion (فضفضة)**:
   - Locked to the single female persona voice **`Aoede`** for consistent identity.
   - Speaks authentic, warm Egyptian Arabic with support for untranslatable English psychiatric terms (`Overthinking`, `Burnout`, `Panic attack`, `Trigger`, `Stress`, `Trauma`, `Safe space`, `ADHD`).
   - Anti-glitch conversation rules: never repeats truncated sentence fragments upon interruption, never restarts sentences from the beginning.
2. **Simplified Conversational Controls**:
   - Single-button conversational flow (`ابدأ الفضفضة`).
   - Natural full-duplex speech detection with automatic turn taking and dynamic barge-in interruption.
3. **5-Phase Clinical AI Pipeline**:
   - **Phase 1: Canonical 10-Prompt Library & JSON Schemas**: Complete clinical contracts conforming to Section 12 & 13.
   - **Phase 2: Pre-Session Context Builder (Prompt 06)**: Dynamically injects authorized patient history and active goals into Gemini Live setup instructions.
   - **Phase 3: In-Session Safety Triage & Protocol Selector (Prompts 02 & 07)**: Parallel 5-tier risk analysis and DBT/CBT grounding tool calling.
   - **Phase 4: Post-Session Clinical Reporting & Memory Reconciliation (Prompts 03, 04, 05, 08)**:
     - `GET /api/session/{id}/detailed-report`: Clinical longitudinal report conforming to `schemas/session_report.schema.json`.
     - `GET /api/session/{id}/recap`: Warm Egyptian Arabic patient letter.
     - `POST /api/session/{id}/extract-memories`: Candidate memory extraction conforming to `schemas/patient_memory.schema.json`.
   - **Phase 5: Evaluation & Normalization (Prompts 09 & 10)**: Clinical boundaries evaluation (`/api/session/{id}/evaluate`) and transcript normalization (`/api/transcript/normalize`).
4. **Egyptian Personal Data Protection Law No. 151/2020 Compliance**:
   - Explicit consent gating before any memory retention.
   - 8 approved non-diagnostic domains (no diagnostic labeling).
   - Automated reconciliation (`ADD`, `UPDATE`, `CONFIRM`, `FLAG_CONFLICT`).
   - Full Right to Erasure (`DELETE /api/patient/{id}/memories/{memory_id}`).
5. **Egyptian National Emergency Hotline Safety System**:
   - Mental Health Hotline (Ministry of Health): `16328` (24/7 free).
   - Egyptian Ambulance Authority: `123`.
6. **Vercel Deployment Ready**:
   - Pre-configured `vercel.json` and `api/index.py` serverless ASGI entrypoint for deploying on Vercel.

---

## 📁 Repository Structure

```
psychiatric_agent/
├── api/
│   └── index.py                    # Vercel Serverless ASGI entrypoint
├── backend/
│   ├── app.py                      # FastAPI application & /ws/live gateway
│   ├── config.py                   # System constants & model definitions
│   ├── storage.py                  # Async SQLite storage (sessions, consents, memories)
│   └── services/
│       ├── gemini_live_bridge.py   # Full-duplex WebSocket bridge to Gemini Live (Aoede)
│       ├── knowledge_service.py    # Protocols & Egyptian crisis directory indexing
│       ├── memory_service.py       # Law 151/2020 memory extraction & reconciliation
│       ├── psychiatric_tools.py    # Function calling declarations for Gemini Live
│       └── report_service.py       # Clinical session reports (P05) & patient recaps (P08)
├── clinical_knowledge/
│   └── protocols.json              # Clinician-reviewed coping exercises (DBT, CBT, breathing)
├── frontend/
│   ├── index.html                  # Main sanctuary web client (RTL, Cairo font)
│   ├── css/style.css               # Design system & responsive UI styles
│   └── js/
│       ├── app.js                  # Client state, WebSocket management & visualizer
│       └── audio-streamer.js       # Studio-grade 16kHz PCM recorder & 24kHz player
├── prompts/                        # Canonical 10-prompt clinical library
│   ├── clinical/therapeutic_protocol_selector.md
│   ├── evaluation/quality_evaluator.md
│   ├── live_agent/system_prompt.md
│   ├── memory/memory_extractor.md
│   ├── memory/memory_reconciler.md
│   ├── memory/session_context_builder.md
│   ├── reporting/detailed_session_report.md
│   ├── reporting/patient_friendly_recap.md
│   ├── safety/safety_signal_analysis.md
│   └── transcription/egyptian_arabic_normalizer.md
├── safety_policies/
│   └── egyptian_crisis_directory.json # Verified emergency hotlines (16328, 123)
├── schemas/                        # Draft-07 JSON schemas for structured outputs
│   ├── patient_memory.schema.json
│   ├── safety_signal.schema.json
│   └── session_report.schema.json
├── .gitignore                      # Ignores databases, secrets, and local others/
├── README.md                       # Project documentation
├── requirements.txt                # Production Python dependencies
├── run.py                          # Local server launcher (python run.py)
├── vercel.json                     # Vercel deployment configuration
└── VERCEL_DEPLOYMENT.md            # Step-by-step Vercel deployment guide
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+
- Google Gemini API Key

### 2. Installation
```bash
git clone https://github.com/omarAbdelaal1/Psychiatric-Agent.git
cd Psychiatric-Agent
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
HOST=0.0.0.0
PORT=8005
MODEL_LIVE=gemini-3.8-live
MODEL_FLASH=gemini-3.8-flash
DEFAULT_VOICE=Aoede
```

### 4. Launch Locally
```bash
python run.py
```
Open your browser to:
- **Web App**: [http://localhost:8005/](http://localhost:8005/)
- **Health Check**: [http://localhost:8005/health](http://localhost:8005/health)
- **Interactive API Docs**: [http://localhost:8005/docs](http://localhost:8005/docs)

---

## ☁️ Deploying on Vercel

1. Import the repository in [Vercel](https://vercel.com/):
   - **Repository**: `omarAbdelaal1/Psychiatric-Agent`
   - **Framework Preset**: Other (detected automatically via `vercel.json`)
2. Set Environment Variables in Vercel Project Settings (**Settings** -> **Environment Variables**):
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `MODEL_LIVE`: `gemini-3.8-live` (Optional, defaults to `gemini-3.8-live`)
   - `MODEL_FLASH`: `gemini-3.8-flash` (Optional, defaults to `gemini-3.8-flash`)
   - `DEFAULT_VOICE`: `Aoede` (Optional, defaults to `Aoede`)
3. Click **Deploy**!

### 💡 How Vercel Streaming Works (Zero User Key Entry):
- **Server-Side Key Security**: The backend serverless endpoint (`GET /api/live-config`) reads `GEMINI_API_KEY` securely from Vercel's encrypted environment variables. End-users/visitors never see, enter, or upload any API key.
- **Direct Full-Duplex Audio**: Because serverless cloud platforms (like Vercel Lambda) do not support long-running incoming WebSockets, the browser client seamlessly connects directly to Google's official Gemini Live WebSocket API using the server-authenticated session config.
- **Seamless Local & Cloud Parity**: The application automatically detects its environment — running via local ASGI gateway (`ws://localhost:8005/ws/live`) on your computer, and via direct low-latency Gemini Live streaming on Vercel.

---

## 🔒 Privacy & Clinical Safety Disclaimer

**فضفضة (Fadfada)** is an artificial intelligence mental health support companion designed for emotional expression and coping assistance. It is **not** a licensed medical doctor, clinical psychiatrist, or diagnostic medical device. 

In situations of acute psychological distress, self-harm concerns, or medical emergencies, users should immediately contact the **Egyptian National Mental Health Hotline at `16328`** or the **Ambulance Service at `123`**. All user data is governed strictly in accordance with **Egyptian Personal Data Protection Law No. 151 of 2020**.
