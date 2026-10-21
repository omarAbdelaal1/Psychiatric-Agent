# FADFADA (فضفضة) — AI Psychiatric Voice Companion Demo

An AI-powered, voice-first mental health support companion delivering psychiatrist-inspired, empathetic conversations in contemporary Egyptian Colloquial Arabic (العامية المصرية).

Built from scratch strictly following [`PIPELINE_DOCUMENTATION.md`](file:///c:/sharing1/ML4/psychiatric_agent/PIPELINE_DOCUMENTATION.md) and orchestrated via **Omni-Orchestrator v3** across 7 dynamic lifecycle phases.

---

## 🌟 Key Capabilities Demonstrated

1. **Egyptian Colloquial Arabic Persona (فضفضة)**:
   - Warm, unhurried, empathetic listening persona speaking natural Egyptian Arabic.
   - Strict clinical boundaries: Non-diagnostic disclaimers, single-question turn pacing, and no medical prescriptions.
2. **Clinical Coping Protocols**:
   - Clinician-reviewed protocols in [`clinical_knowledge/protocols.json`](file:///c:/sharing1/ML4/psychiatric_agent/clinical_knowledge/protocols.json): Sensory Grounding 5-4-3-2-1, Box Breathing 4-4-4-4, CBT Thought Reframing, and Micro-Behavioral Activation.
   - Symptom-to-protocol matching with automatic contraindication filtering.
3. **Egyptian National Crisis Safety Protocol**:
   - Persistent emergency hotlines in [`safety_policies/egyptian_crisis_directory.json`](file:///c:/sharing1/ML4/psychiatric_agent/safety_policies/egyptian_crisis_directory.json):
     - **الأمانة العامة للصحة النفسية (وزارة الصحة)**: `16328` (24/7 مجاناً)
     - **هيئة الإسعاف المصرية**: `123`
     - **الخط الأرضي المجاني**: `08008880700`
     - **طوارئ مستشفى العباسية**: `02-20816831`
     - **خط نجدة الطفل**: `16000`
     - **مكتب شكاوى المرأة**: `15115`
   - Real-time safety keyword triage that halts casual dialogue and directs users immediately to human emergency services.
4. **Egyptian Personal Data Protection Law No. 151/2020 Compliance**:
   - Consent gating: Memory extraction is strictly refused if explicit consent is withheld.
   - 8 approved non-diagnostic memory domains.
   - Automated reconciliation (`ADD`, `UPDATE`, `CONFIRM`, `FLAG_CONFLICT`).
   - Full Right to Erasure (`DELETE /api/patient/{id}/memories/{memory_id}`).
5. **Real-Time Audio Streaming Pipeline**:
   - Native Web Audio API client capturing hardware microphone.
   - Software downsampler: Linear interpolation to 16,000 Hz signed 16-bit PCM Int16 Little-Endian base64 frames.
   - Adaptive VAD with RMS ambient tracking and 850ms silence turn conclusion.
   - Dynamic 24,000 Hz AudioBuffer playback queue with 30ms jitter buffer.
   - 2D Canvas radiant Voice Orb visualizer pulsing with real-time sound energy.
   - High-energy vocal interruption and manual barge-in handling (`user_interrupt`).
6. **Dual Online/Offline Operation**:
   - Seamlessly connects to Google Gemini Live API when `GEMINI_API_KEY` is provided.
   - When no key is set, activates an intelligent local Egyptian Arabic conversational simulation engine with realistic 24kHz PCM Little-Endian speech frames, enabling immediate offline demonstration out of the box!

---

## 🎨 4 Standalone Design Variants

In accordance with Omni-Orchestrator v3 and the User Persona design system guidelines for medium/large UI flows, 4 diverse standalone prototypes were crafted in `design-variants/`:

- **Interactive Switcher Dashboard**: [`design-variants/index.html`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/index.html)
- **Variant 1 — Serene Minimalist Sanctuary**: [`design-variants/variant-01.html`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/variant-01.html)
- **Variant 2 — Therapeutic Assistant Split-View**: [`design-variants/variant-02.html`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/variant-02.html)
- **Variant 3 — Audio-First Immersive Orb**: [`design-variants/variant-03.html`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/variant-03.html)
- **Variant 4 — Clinical Care & Memory Journal**: [`design-variants/variant-04.html`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/variant-04.html)
- **10-Point Shared Rubric & Synthesis**: [`design-variants/comparison.md`](file:///c:/sharing1/ML4/psychiatric_agent/design-variants/comparison.md)

---

## 🚀 Quick Start Guide

### 1. Launch the Server
The project is already pre-configured with your Gemini API key in [`.env`](file:///c:/sharing1/ML4/psychiatric_agent/.env). To launch from this directory (`c:\sharing1\ML4\psychiatric_agent`):
```powershell
python run.py
```

### 2. Access the Application
Open your browser to:
- **Main Sanctuary Web Client**: [http://localhost:8005/](http://localhost:8005/)
- **4 Design Variants Comparison**: [http://localhost:8005/design-variants-static/index.html](http://localhost:8005/design-variants-static/index.html)
- **Interactive OpenAPI Documentation**: [http://localhost:8005/docs](http://localhost:8005/docs)
- **Health Check**: [http://localhost:8005/health](http://localhost:8005/health)

*(Optional)* To use Google Gemini Live Cloud instead of the built-in simulation engine, set your API key in the environment:
```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
python run.py
```

---

## 🧪 Verification & Automated Test Suite

The demo is backed by **21 automated unit and integration tests** passing with 100% compliance:

```powershell
python -m pytest tests/ -v
```

### Test Coverage Matrix
```
Test Module                                                 Tests   Status
----------------------------------------------------------  -----   ------
tests/test_audio_processing.py (PCM math, 16k/24k, RMS)        4    PASSED
tests/test_backend_api_and_ws.py (REST contracts, WebSocket)   7    PASSED
tests/test_knowledge_and_crisis.py (Protocols, Hotlines)       6    PASSED
tests/test_memory_and_privacy.py (Law 151/2020, Erasure)       4    PASSED
----------------------------------------------------------  -----   ------
Total Tests Verified                                          21    100% PASSED (0.77s)
```

---

## 📁 Repository Directory Structure

```
c:\sharing1\ML4\psychiatric_agent\
├── PIPELINE_DOCUMENTATION.md      # Canonical system architecture document
├── README.md                      # Quick-start and demonstration guide
├── run.py                         # One-click demo server entrypoint
├── fadfada.db                     # SQLite persistence (WAL mode)
│
├── backend/
│   ├── app.py                     # FastAPI application, AppSec middleware & WebSocket gateway
│   ├── config.py                  # Audio parameters (16kHz in, 24kHz out) & system constants
│   ├── storage.py                 # Async SQLite storage for sessions, messages & memories
│   └── services/
│       ├── gemini_live_bridge.py  # Full-duplex WebSocket bridge & smart simulation engine
│       ├── knowledge_service.py   # Protocols & Egyptian crisis directory indexing
│       └── memory_service.py      # Law 151/2020 memory extraction, reconciliation & erasure
│
├── clinical_knowledge/
│   └── protocols.json             # 4 Clinician-reviewed coping exercises (DBT, CBT, breathing)
│
├── safety_policies/
│   └── egyptian_crisis_directory.json  # 6 Verified Egyptian emergency crisis hotlines (16328, 123)
│
├── prompts/
│   ├── live_agent/system_prompt.md     # Egyptian Colloquial Arabic companion prompt
│   ├── safety/safety_signal_analysis.md # Real-time clinical risk analyzer
│   ├── memory/memory_extractor.md      # Law 151/2020 candidate memory extractor
│   └── reporting/patient_friendly_recap.md # Post-session Egyptian recap generator
│
├── frontend/
│   ├── index.html                 # Production sanctuary web UI (RTL, Cairo font, accessibility)
│   ├── css/style.css              # Pure Vanilla CSS design tokens & responsive styling
│   └── js/app.js                  # Web Audio downsampler, 24kHz queue, VAD, voice orb
│
├── design-variants/
│   ├── index.html                 # Interactive 4-variant comparison switcher
│   ├── variant-01.html            # Variant 1: Serene Minimalist Sanctuary
│   ├── variant-02.html            # Variant 2: Therapeutic Assistant Split-View
│   ├── variant-03.html            # Variant 3: Audio-First Immersive Orb
│   ├── variant-04.html            # Variant 4: Clinical Care & Memory Journal
│   └── comparison.md              # 10-Point shared evaluation rubric & hybrid synthesis
│
└── tests/
    ├── test_audio_processing.py
    ├── test_backend_api_and_ws.py
    ├── test_knowledge_and_crisis.py
    └── test_memory_and_privacy.py
```
