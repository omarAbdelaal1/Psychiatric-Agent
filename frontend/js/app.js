/**
 * FADFADA (فضفضة) — Master Web Audio & Full-Duplex Live Streaming Client
 * Architecture:
 * 1. Single locked female Aoede voice configuration.
 * 2. Studio-grade AudioStreamer with native 24kHz upsampling, boundary micro-blending, & immediate gain un-ducking.
 * 3. Dual-Mode Seamless Transport:
 *    - Cloud / Serverless (Vercel): Direct Gemini Live WebSocket with zero user key input (auto-fetched from /api/live-config).
 *    - Local Development: ASGI WebSocket Gateway (/ws/live) with automatic fallback to Direct Gemini Live.
 * 4. Full-duplex interruption & barge-in handling.
 * 5. Egyptian psychiatric clinical protocols, grounding tools, and Law 151/2020 privacy compliance.
 */

class FadfadaClient {
  constructor() {
    this.socket = null;            // Local gateway WebSocket (if running locally)
    this.geminiSocket = null;      // Direct Gemini Live WebSocket (for cloud/serverless)
    this.isDirectGemini = false;
    this.isConnecting = false;
    this.liveConfig = null;

    this.isRecording = false;
    this.isPlayingAgentAudio = false;
    this.patientId = 'default_user';
    this.sessionId = 'sess_' + Date.now();
    this.audioGeneration = 0;
    this.isManualInterruptActive = false;

    // Buffer for recording conversation turns to backend storage
    this.currentTurnUserText = '';
    this.currentTurnAgentText = '';

    // Visualizer energy metrics
    this.userRMS = 0;
    this.orbPhase = 0;

    // Active streaming message elements
    this.activeUserMsgElem = null;
    this.activeAgentMsgElem = null;
    this.userUtteranceTimer = null;

    // DOM Elements
    this.canvas = document.getElementById('voiceOrbCanvas');
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    this.orbStatusText = document.getElementById('orbStatusText');
    this.conversationFeed = document.getElementById('conversationFeed');
    this.streamingInterimCard = document.getElementById('streamingInterimCard');
    this.streamingSpeakerTag = document.getElementById('streamingSpeakerTag');
    this.streamingInterimText = document.getElementById('streamingInterimText');

    this.btnStartVoice = document.getElementById('btnStartVoice');
    this.btnRecordLabel = document.getElementById('btnRecordLabel');

    // Instantiate studio-grade AudioStreamer with native full-duplex streaming
    this.audioStreamer = new AudioStreamer({
      onAudioChunk: (base64Audio) => {
        if (!this.isRecording) return;

        if (this.isDirectGemini && this.geminiSocket && this.geminiSocket.readyState === WebSocket.OPEN) {
          // Direct Gemini Live uplink format (16kHz PCM Mono)
          this.geminiSocket.send(JSON.stringify({
            realtimeInput: {
              mediaChunks: [
                {
                  mimeType: 'audio/pcm;rate=16000',
                  data: base64Audio
                }
              ]
            }
          }));
        } else if (this.socket && this.socket.readyState === WebSocket.OPEN) {
          // Local gateway format
          this.socket.send(JSON.stringify({
            type: 'audio',
            data: base64Audio
          }));
        }
      },
      onMicLevel: (level) => {
        this.userRMS = level;
      },
      onPlaybackStateChange: (isPlaying) => {
        this.isPlayingAgentAudio = isPlaying;
        if (!this.isDirectGemini && this.socket && this.socket.readyState === WebSocket.OPEN) {
          this.socket.send(JSON.stringify({
            type: 'playback_state',
            is_playing: isPlaying
          }));
        }
        if (isPlaying) {
          this.setStatus('فضفضة تتحدث..');
        } else {
          this.setStatus(this.isRecording ? 'أنا سامعاكِ.. اتفضلي اتكلمي' : 'مستعدة للحديث');
        }
      }
    });

    this.initVisualizer();
    this.initConnection();
    this.loadProtocols();
    this.loadCrisisDirectory();
    this.loadPatientConsent();
  }

  // =========================================================================
  // Connection Orchestration (Local Gateway vs Cloud Direct Gemini Live)
  // =========================================================================
  async initConnection() {
    if (this.isConnecting) return;
    this.isConnecting = true;

    const hostname = window.location.hostname;
    const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1' || hostname.startsWith('192.168.');
    const isVercel = hostname.includes('vercel.app') || hostname.includes('now.sh');

    const urlParams = new URLSearchParams(window.location.search);
    const forceDirect = urlParams.get('mode') === 'direct';
    const forceGateway = urlParams.get('mode') === 'gateway';

    // On Vercel / serverless cloud environments, incoming WebSockets are not supported.
    // Seamlessly connect directly to Gemini Live using server-provided session configuration.
    if (isVercel || forceDirect || !isLocalhost) {
      console.log('[Fadfada] Cloud / Vercel environment detected. Using Direct Gemini Live streaming...');
      await this.connectDirectGemini();
    } else if (forceGateway || isLocalhost) {
      console.log('[Fadfada] Local environment detected. Attempting local ASGI gateway...');
      this.connectLocalGateway();
    } else {
      await this.connectDirectGemini();
    }
  }

  // -------------------------------------------------------------------------
  // Direct Gemini Live WebSocket (Cloud / Vercel Serverless)
  // -------------------------------------------------------------------------
  async connectDirectGemini() {
    try {
      this.setStatus('جارٍ إعداد جلسة الفضفضة..');
      console.log('[Fadfada] Fetching live config from serverless backend (/api/live-config)...');

      const res = await fetch(`/api/live-config?patient_id=${encodeURIComponent(this.patientId)}`);
      if (!res.ok) {
        throw new Error(`Failed to load session config: HTTP ${res.status}`);
      }

      const config = await res.json();
      this.liveConfig = config;

      if (!config.has_api_key || !config.ws_url) {
        console.error('[Fadfada] No GEMINI_API_KEY available from server environment.');
        this.setStatus('⚠️ مفتاح GEMINI_API_KEY غير موجود في إعدادات البيئة (Vercel Variables)');
        this.addMessage(
          '⚠️ لم يتم العثور على مفتاح GEMINI_API_KEY في إعدادات الخادم (Environment Variables). يرجى إضافة المفتاح في لوحة تحكم Vercel وإعادة تشغيل النشر.',
          'agent'
        );
        this.isConnecting = false;
        return;
      }

      console.log('[Fadfada] Connecting directly to Gemini Live with model:', config.model);
      this.geminiSocket = new WebSocket(config.ws_url);
      this.isDirectGemini = true;

      this.geminiSocket.onopen = () => {
        console.log('[Fadfada] Direct Gemini Live WebSocket connected. Dispatching setup frame...');
        const setupMessage = {
          setup: {
            model: `models/${config.model || 'gemini-3.8-live'}`,
            generationConfig: {
              responseModalities: ['AUDIO'],
              speechConfig: {
                voiceConfig: {
                  prebuiltVoiceConfig: {
                    voiceName: config.voice || 'Aoede'
                  }
                }
              }
            },
            outputAudioTranscription: {},
            systemInstruction: {
              parts: [{ text: config.system_instruction }]
            },
            tools: config.tools || []
          }
        };
        this.geminiSocket.send(JSON.stringify(setupMessage));
      };

      this.geminiSocket.onmessage = async (event) => {
        try {
          let dataText = event.data;
          if (dataText instanceof Blob) {
            dataText = await dataText.text();
          }
          const msg = JSON.parse(dataText);
          this.handleDirectGeminiMessage(msg);
        } catch (err) {
          console.error('[Fadfada] Failed to parse Gemini Live packet:', err);
        }
      };

      this.geminiSocket.onerror = (err) => {
        console.error('[Fadfada] Direct Gemini Live WebSocket error:', err);
      };

      this.geminiSocket.onclose = (ev) => {
        console.warn(`[Fadfada] Direct Gemini WebSocket closed (code ${ev.code}). Reconnecting in 3s...`);
        this.isConnecting = false;
        setTimeout(() => this.connectDirectGemini(), 3000);
      };

      this.isConnecting = false;
    } catch (err) {
      console.error('[Fadfada] Direct Gemini initialization error:', err);
      this.setStatus('تعذر إعداد الاتصال.. جاري إعادة المحاولة');
      this.isConnecting = false;
      setTimeout(() => this.connectDirectGemini(), 3000);
    }
  }

  handleDirectGeminiMessage(msg) {
    // 1. Initial Setup Acknowledgement
    if (msg.setupComplete) {
      this.setStatus('مستعدة للحديث');
      console.log('[Fadfada] Direct Gemini Live ready! Locked Female Voice: Aoede');
      return;
    }

    // 2. Server Content: Audio downlink, transcriptions, and barge-in interrupts
    const sc = msg.serverContent;
    if (sc) {
      // Barge-in / Interruption detected by Gemini's native server VAD
      if (sc.interrupted) {
        this.audioGeneration++;
        console.log(`[Fadfada] Generation interrupted by user speech (generation_id: ${this.audioGeneration})`);
        this.audioStreamer.stopPlayback();
        this.hideInterimCard();
        this.sealActiveAgentBubble();
        this.sealActiveUserBubble();
        this.setStatus('أنا سامعاكِ.. اتفضلي اتكلمي');
      }

      // Spoken User Transcription (Gemini internal STT)
      const inTrans = sc.inputTranscription || msg.inputTranscription;
      if (inTrans && inTrans.text) {
        this.appendUserTranscription(inTrans.text);
        this.currentTurnUserText = this.smartAppendArabicText(this.currentTurnUserText, inTrans.text);
        this.checkClientCrisisSignals(inTrans.text);
      }

      // Spoken Agent Output Transcription
      const outTrans = sc.outputTranscription || msg.outputTranscription;
      if (outTrans && outTrans.text) {
        this.appendAgentText(outTrans.text);
        this.currentTurnAgentText = this.smartAppendArabicText(this.currentTurnAgentText, outTrans.text);
      }

      // 24kHz PCM Audio Downlink
      if (!sc.interrupted && sc.modelTurn && sc.modelTurn.parts) {
        for (const part of sc.modelTurn.parts) {
          if (part.inlineData && part.inlineData.data) {
            this.sealActiveUserBubble();
            this.audioStreamer.playAudioChunk(part.inlineData.data);
          }
        }
      }

      // Turn Complete: Flush turn to persistent serverless database
      if (sc.turnComplete || sc.generationComplete) {
        this.recordTurnToBackend();
        this.sealActiveUserBubble();
        this.sealActiveAgentBubble();
        this.hideInterimCard();
        this.setStatus(this.isRecording ? 'أنا سامعاكِ.. اتفضلي اتكلمي' : 'مستعدة للحديث');
      }
    }

    // 3. Clinical Tool Calls (Grounding, Crisis Escalation, Protocols)
    const toolCall = msg.toolCall || (sc && sc.toolCall);
    if (toolCall && toolCall.functionCalls) {
      this.handleGeminiToolCalls(toolCall.functionCalls);
    }
  }

  async handleGeminiToolCalls(functionCalls) {
    const functionResponses = [];

    for (const call of functionCalls) {
      const callId = call.id;
      const name = call.name;
      const args = call.args || {};
      console.log(`[Fadfada] Executing clinical tool: ${name}`, args);

      let result = {};

      if (name === 'trigger_grounding_exercise') {
        const exercise = args.exercise_name || 'square_breathing';
        const title = exercise === 'square_breathing' ? 'التنفس المربع (4-4-4)' : 'تمرين الحواس الخمس (5-4-3-2-1)';
        const guidance = args.guidance_ar || (exercise === 'square_breathing'
          ? 'خد نفس هادي في 4 ثواني.. واكتمه 4 ثواني.. وازفر براحة في 4 ثواني..'
          : 'بص حواليك ولاحظ 5 حاجات شايفها، و4 حاجات حاسس بيها ملموسة..');

        this.showGroundingExercise({
          exercise: exercise,
          title_ar: title,
          guidance_ar: guidance
        });

        result = {
          status: 'success',
          exercise: exercise,
          title_ar: title,
          guidance_ar: guidance,
          instruction: 'Explain the step calmly in one gentle sentence in Egyptian Arabic and invite the user to breathe or observe.'
        };
      } else if (name === 'escalate_crisis') {
        const urgency = args.urgency_level || 'immediate';
        this.showCrisisAlert({
          primary_hotline: '16328',
          ambulance: '123',
          urgency: urgency
        });

        result = {
          status: 'escalated',
          urgency: urgency,
          primary_hotline: {
            name: 'الخط الساخن للأمانة العامة للصحة النفسية وعلاج الإدمان (MOHP)',
            number: '16328',
            availability: '24/7 مجاناً'
          },
          ambulance: '123',
          instruction: 'Urge the patient warmly to contact 16328 or 123 immediately and assure them that their life and safety are the top priority.'
        };
      } else if (name === 'select_therapeutic_protocol') {
        result = {
          status: 'selected',
          protocol: {
            id: 'cbt_worry_postponement',
            title_ar: 'تأجيل القلق وتفنيد الأفكار',
            evidence_base: 'CBT / ACT'
          }
        };
      } else {
        result = { status: 'ok' };
      }

      functionResponses.push({
        id: callId,
        response: { output: result }
      });
    }

    if (this.geminiSocket && this.geminiSocket.readyState === WebSocket.OPEN) {
      this.geminiSocket.send(JSON.stringify({
        toolResponse: { functionResponses }
      }));
      console.log('[Fadfada] Clinical tool responses dispatched back to Gemini Live');
    }
  }

  // -------------------------------------------------------------------------
  // Local ASGI Gateway WebSocket (Localhost Development)
  // -------------------------------------------------------------------------
  connectLocalGateway() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;
    console.log('[Fadfada] Connecting local WebSocket gateway:', wsUrl);

    let connectionOpened = false;
    this.socket = new WebSocket(wsUrl);

    // If local gateway fails to open within 3.5s, fall back to Direct Gemini Live
    const fallbackTimer = setTimeout(() => {
      if (!connectionOpened) {
        console.warn('[Fadfada] Local gateway handshake timed out. Falling back to Direct Gemini Live...');
        try { this.socket.close(); } catch (e) {}
        this.connectDirectGemini();
      }
    }, 3500);

    this.socket.onopen = () => {
      connectionOpened = true;
      clearTimeout(fallbackTimer);
      this.isDirectGemini = false;
      this.isConnecting = false;
      console.log('[Fadfada] Local gateway WebSocket connected.');
      this.socket.send(JSON.stringify({
        type: 'init',
        voice: 'Aoede',
        session_id: this.sessionId,
        patient_id: this.patientId
      }));
    };

    this.socket.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleServerMessage(msg);
      } catch (err) {
        console.error('[Fadfada] Failed to parse gateway message:', err);
      }
    };

    this.socket.onerror = (err) => {
      console.warn('[Fadfada] Local gateway WebSocket error:', err);
      if (!connectionOpened) {
        clearTimeout(fallbackTimer);
        console.log('[Fadfada] Switching to Direct Gemini Live due to gateway error...');
        this.connectDirectGemini();
      }
    };

    this.socket.onclose = () => {
      if (connectionOpened) {
        console.warn('[Fadfada] Local gateway WebSocket closed. Reconnecting in 3s..');
        setTimeout(() => this.connectLocalGateway(), 3000);
      }
    };
  }

  handleServerMessage(msg) {
    switch (msg.type) {
      case 'ready':
        this.setStatus('مستعدة للحديث');
        console.log('[Fadfada] Server ready. Locked Voice: Aoede, Model:', msg.model);
        break;

      case 'audio': {
        const gen = Number(msg.generation_id ?? 0);
        if (gen < this.audioGeneration) {
          console.log(`[Fadfada] Discarding stale audio chunk from generation ${gen} (active: ${this.audioGeneration})`);
          break;
        }
        this.audioGeneration = gen;
        this.sealActiveUserBubble();
        if (msg.data) {
          this.audioStreamer.playAudioChunk(msg.data);
        }
        break;
      }

      case 'user_transcription':
      case 'user_text':
        this.appendUserTranscription(msg.text);
        this.checkClientCrisisSignals(msg.text);
        break;

      case 'agent_text':
      case 'model_transcription':
        this.appendAgentText(msg.text);
        break;

      case 'interrupted': {
        const incomingGen = Number(msg.generation_id ?? 0);
        this.audioGeneration = Math.max(this.audioGeneration + 1, incomingGen);
        console.log(`[Fadfada] Interrupted signal received (generation: ${this.audioGeneration})`);
        this.audioStreamer.stopPlayback();
        this.hideInterimCard();
        this.sealActiveAgentBubble();
        this.sealActiveUserBubble();
        this.setStatus('أنا سامعاكِ.. اتفضلي اتكلمي');
        break;
      }

      case 'turn_complete': {
        const turnGen = Number(msg.generation_id ?? 0);
        if (turnGen >= this.audioGeneration) {
          this.audioGeneration = turnGen;
        }
        this.sealActiveUserBubble();
        this.sealActiveAgentBubble();
        this.hideInterimCard();
        this.setStatus(this.isRecording ? 'أنا سامعاكِ.. اتفضلي اتكلمي' : 'مستعدة للحديث');
        break;
      }

      case 'grounding_triggered':
        this.showGroundingExercise(msg);
        break;

      case 'crisis_alert':
        this.showCrisisAlert(msg);
        break;
    }
  }

  // =========================================================================
  // Client-Side Emergency Signal Detection
  // =========================================================================
  checkClientCrisisSignals(text) {
    if (!text) return;
    const crisisPatterns = /(انتحر|عايز\s*اموت|أموت|أنهي\s*حياتي|انهي\s*حياتي|مش\s*قادر\s*اعيش|مش\s*قادرة\s*اعيش|اذي\s*نفسي|أذي\s*نفسي|انتحار)/i;
    if (crisisPatterns.test(text)) {
      this.showCrisisAlert({
        primary_hotline: '16328',
        ambulance: '123',
        urgency: 'immediate'
      });
    }
  }

  recordTurnToBackend() {
    const userFinal = this.currentTurnUserText.trim();
    const agentFinal = this.currentTurnAgentText.trim();
    if (userFinal || agentFinal) {
      fetch(`/api/session/${encodeURIComponent(this.sessionId)}/record-turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: this.patientId,
          user_text: userFinal,
          agent_text: agentFinal
        })
      }).catch((err) => console.warn('[Fadfada] Failed to record turn to backend:', err));
    }
    this.currentTurnUserText = '';
    this.currentTurnAgentText = '';
  }

  // =========================================================================
  // Dialogue Message Feed Management
  // =========================================================================
  smartAppendArabicText(existing, chunk) {
    if (!chunk) return existing || '';
    if (!existing || existing.trim().length === 0) return chunk.trimStart();

    const cleanChunk = chunk.trim();
    const cleanExisting = existing.trim();

    // Word-level boundary overlap deduplicator
    const existWords = cleanExisting.split(/\s+/);
    const chunkWords = cleanChunk.split(/\s+/);

    const maxOverlap = Math.min(existWords.length, chunkWords.length, 5);
    for (let n = maxOverlap; n > 0; n--) {
      const existTail = existWords.slice(-n).join(' ');
      const chunkHead = chunkWords.slice(0, n).join(' ');
      if (existTail === chunkHead) {
        const remaining = chunkWords.slice(n).join(' ');
        if (!remaining) return existing;
        return existing + ' ' + remaining;
      }
    }

    const lastChar = existing.slice(-1);
    const firstChar = chunk.charAt(0);
    const attachedPunctuation = new Set(['.', '،', '؟', '!', ',', '?', ':', ';', '؛', ')', ']', '}', '»', '”']);

    if (attachedPunctuation.has(firstChar)) {
      return existing.trimEnd() + chunk;
    }

    if (/\s/.test(lastChar) || /\s/.test(firstChar)) {
      return existing + chunk;
    }

    return existing + ' ' + chunk;
  }

  sealActiveUserBubble() {
    if (this.userUtteranceTimer) {
      clearTimeout(this.userUtteranceTimer);
      this.userUtteranceTimer = null;
    }
    this.activeUserMsgElem = null;
  }

  sealActiveAgentBubble() {
    this.activeAgentMsgElem = null;
  }

  appendUserTranscription(chunk) {
    if (!chunk || !chunk.trim()) return;
    const clean = this.sanitizeASR(chunk);
    if (!clean) return;

    this.sealActiveAgentBubble();

    if (this.conversationFeed) {
      if (!this.activeUserMsgElem) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-message message-user';
        msgDiv.innerHTML = `
          <div class="message-meta">
            <span class="sender-tag">أنت 👤</span>
            <span class="time-tag">${this.getNowTime()}</span>
          </div>
          <div class="message-bubble"></div>
        `;
        this.conversationFeed.appendChild(msgDiv);
        this.activeUserMsgElem = msgDiv.querySelector('.message-bubble');
      }

      this.activeUserMsgElem.textContent = this.smartAppendArabicText(this.activeUserMsgElem.textContent, clean);
      this.scrollFeedToBottom();
      this.showInterimCard('أنت تتحدث الآن...', this.activeUserMsgElem.textContent);
    }

    if (this.userUtteranceTimer) clearTimeout(this.userUtteranceTimer);
    this.userUtteranceTimer = setTimeout(() => {
      this.sealActiveUserBubble();
    }, 1500);
  }

  appendAgentText(chunk) {
    if (!chunk || !chunk.trim()) return;
    const clean = this.sanitizeASR(chunk);
    if (!clean) return;

    this.sealActiveUserBubble();

    if (this.conversationFeed) {
      if (!this.activeAgentMsgElem) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-message message-agent';
        msgDiv.innerHTML = `
          <div class="message-meta">
            <span class="sender-tag">فضفضة 🌿</span>
            <span class="time-tag">${this.getNowTime()}</span>
          </div>
          <div class="message-bubble"></div>
        `;
        this.conversationFeed.appendChild(msgDiv);
        this.activeAgentMsgElem = msgDiv.querySelector('.message-bubble');
      }

      this.activeAgentMsgElem.textContent = this.smartAppendArabicText(this.activeAgentMsgElem.textContent, clean);
      this.scrollFeedToBottom();
      this.showInterimCard('فضفضة تتحدث الآن...', this.activeAgentMsgElem.textContent);
    }
  }

  showInterimCard(speakerLabel, interimText) {
    if (this.streamingInterimCard && this.streamingSpeakerTag && this.streamingInterimText) {
      this.streamingSpeakerTag.textContent = speakerLabel;
      this.streamingInterimText.textContent = interimText;
      this.streamingInterimCard.style.display = 'flex';
      this.scrollFeedToBottom();
    }
  }

  hideInterimCard() {
    if (this.streamingInterimCard) {
      this.streamingInterimCard.style.display = 'none';
    }
  }

  addMessage(text, sender = 'agent', isCrisis = false) {
    if (!this.conversationFeed || !text) return;

    const sanitized = this.sanitizeASR(text);
    if (!sanitized) return;

    this.sealActiveUserBubble();
    this.sealActiveAgentBubble();

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message message-${sender} ${isCrisis ? 'message-crisis' : ''}`;

    const senderTitle = sender === 'user' ? 'أنت 👤' : 'فضفضة 🌿';

    messageDiv.innerHTML = `
      <div class="message-meta">
        <span class="sender-tag">${senderTitle}</span>
        <span class="time-tag">${this.getNowTime()}</span>
      </div>
      <div class="message-bubble">${sanitized}</div>
    `;

    this.conversationFeed.appendChild(messageDiv);
    this.scrollFeedToBottom();
  }

  getNowTime() {
    const now = new Date();
    return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
  }

  scrollFeedToBottom() {
    if (this.conversationFeed) {
      this.conversationFeed.scrollTop = this.conversationFeed.scrollHeight;
    }
  }

  sanitizeASR(rawText) {
    if (!rawText) return '';
    return rawText
      .replace(/<thought>[\s\S]*?<\/thought>/gi, '')
      .replace(/<[^>]+>/gi, '')
      .replace(/\[.*?\]/g, '')
      .trim();
  }

  // =========================================================================
  // User Actions & Voice Session Control
  // =========================================================================
  async toggleVoiceSession() {
    if (this.isRecording) {
      this.stopAudioCapture();
    } else {
      await this.startAudioCapture();
    }
  }

  async startAudioCapture() {
    try {
      this.audioStreamer.initAudioContext();
      await this.audioStreamer.startRecording();
      this.isRecording = true;
      this.updateControlsUI();
      this.setStatus('أنا سامعاكِ.. اتفضلي اتكلمي');
      console.log('[Fadfada] Microphone capture started via AudioStreamer');
    } catch (err) {
      console.error('[Fadfada] Mic access failed:', err);
      alert('يرجى السماح بالوصول إلى الميكروفون لبدء الفضفضة الصوتية.');
    }
  }

  stopAudioCapture() {
    this.isRecording = false;
    this.audioStreamer.stopRecording();
    this.audioStreamer.stopPlayback();
    this.sealActiveUserBubble();
    this.sealActiveAgentBubble();
    this.hideInterimCard();
    this.updateControlsUI();
    this.setStatus('مستعدة للحديث');
    console.log('[Fadfada] Microphone capture stopped');
  }

  triggerBargeIn() {
    this.isManualInterruptActive = true;
    this.audioStreamer.stopPlayback();
    this.sealActiveUserBubble();
    this.sealActiveAgentBubble();
    this.hideInterimCard();
    this.setStatus('أنا سامعاكِ.. اتفضلي اتكلمي');

    if (this.isDirectGemini && this.geminiSocket && this.geminiSocket.readyState === WebSocket.OPEN) {
      this.audioGeneration++;
      this.geminiSocket.send(JSON.stringify({
        clientContent: { turnComplete: true }
      }));
    } else if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'user_interrupt' }));
    }

    setTimeout(() => {
      this.isManualInterruptActive = false;
    }, 1500);
  }

  sendTypedTurn() {
    const input = document.getElementById('typedInput');
    const text = input ? input.value.trim() : '';
    if (!text) return;

    this.addMessage(text, 'user');
    if (input) input.value = '';

    this.checkClientCrisisSignals(text);

    if (this.isDirectGemini && this.geminiSocket && this.geminiSocket.readyState === WebSocket.OPEN) {
      this.currentTurnUserText = text;
      this.geminiSocket.send(JSON.stringify({
        clientContent: {
          turns: [
            {
              role: 'user',
              parts: [{ text: text }]
            }
          ],
          turnComplete: true
        }
      }));
      this.setStatus('فضفضة تفكر بالرد..');
    } else if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({
        type: 'text',
        text: text
      }));
      this.setStatus('فضفضة تكتب رداً..');
    }
  }

  // =========================================================================
  // Canvas Voice Orb Visualizer
  // =========================================================================
  initVisualizer() {
    if (!this.canvas || !this.ctx) return;

    const render = () => {
      this.orbPhase += 0.04;
      const width = this.canvas.width;
      const height = this.canvas.height;
      const centerX = width / 2;
      const centerY = height / 2;

      this.ctx.clearRect(0, 0, width, height);

      // Extract frequency data from AudioStreamer
      const freqData = this.audioStreamer.getVisualizerData();
      let freqSum = 0;
      for (let i = 0; i < 16; i++) {
        freqSum += freqData[i] || 0;
      }
      const freqAvg = freqSum / (16 * 255.0);

      // Determine active energy
      const liveEnergy = Math.max(this.userRMS * 2.2, freqAvg * 2.5, 0.05);
      const baseRadius = 55 + liveEnergy * 45;

      // Draw subtle ripple waves
      const waveCount = 3;
      for (let i = 1; i <= waveCount; i++) {
        const waveRadius = baseRadius + (i * 22) + (Math.sin(this.orbPhase + i) * 6);
        this.ctx.beginPath();
        this.ctx.arc(centerX, centerY, waveRadius, 0, Math.PI * 2);
        this.ctx.strokeStyle = `rgba(16, 185, 129, ${0.25 / i})`;
        this.ctx.lineWidth = 1.5;
        this.ctx.stroke();
      }

      // Draw Glowing Central Radial Orb
      const gradient = this.ctx.createRadialGradient(
        centerX - 15, centerY - 15, 5,
        centerX, centerY, baseRadius
      );

      if (this.isRecording && this.audioStreamer.isUserSpeaking) {
        // User speaking: warm vibrant emerald glow
        gradient.addColorStop(0, '#a7f3d0');
        gradient.addColorStop(0.4, '#10b981');
        gradient.addColorStop(0.8, '#047857');
        gradient.addColorStop(1, '#064e3b');
      } else if (this.isPlayingAgentAudio) {
        // Agent speaking: serene radiant cyan/teal glow
        gradient.addColorStop(0, '#cffafe');
        gradient.addColorStop(0.4, '#06b6d4');
        gradient.addColorStop(0.8, '#0e7490');
        gradient.addColorStop(1, '#164e63');
      } else {
        // Idle gentle breathing glow
        gradient.addColorStop(0, '#6ee7b7');
        gradient.addColorStop(0.5, '#059669');
        gradient.addColorStop(1, '#022c22');
      }

      this.ctx.beginPath();
      this.ctx.arc(centerX, centerY, baseRadius, 0, Math.PI * 2);
      this.ctx.fillStyle = gradient;
      this.ctx.shadowColor = 'rgba(16, 185, 129, 0.5)';
      this.ctx.shadowBlur = 30 + (liveEnergy * 30);
      this.ctx.fill();

      requestAnimationFrame(render);
    };

    render();
  }

  // =========================================================================
  // UI Helpers & Formatting
  // =========================================================================
  setStatus(text) {
    if (this.orbStatusText) this.orbStatusText.textContent = text;
  }

  updateControlsUI() {
    if (this.btnStartVoice) {
      if (this.isRecording) {
        this.btnStartVoice.classList.add('recording');
        if (this.btnRecordLabel) this.btnRecordLabel.textContent = 'إيقاف الفضفضة';
      } else {
        this.btnStartVoice.classList.remove('recording');
        if (this.btnRecordLabel) this.btnRecordLabel.textContent = 'ابدأ الفضفضة';
      }
    }
  }

  showGroundingExercise(msg) {
    const exerciseTitle = msg.title_ar || 'تمرين تهدئة وتنفس';
    const exerciseGuidance = msg.guidance_ar || 'خد شهيق هادي واكتمه وازفر ببطء..';
    this.setStatus(`🌿 ${exerciseTitle}`);
    this.addMessage(`🌿 **${exerciseTitle}**\n${exerciseGuidance}`, 'agent');
  }

  showCrisisAlert(msg) {
    const hotline = msg.primary_hotline || '16328';
    const ambulance = msg.ambulance || '123';
    this.setStatus('🚨 تنبيه أمان: خط الدعم النفسي 16328');
    this.addMessage(
      `سلامتك هي أهم حاجة دلوقتي.. أرجوك اتصل فوراً بالخط الساخن للأمانة العامة للصحة النفسية: ${hotline} (مجاناً 24 ساعة) أو الإسعاف ${ambulance}.`,
      'agent',
      true
    );
    openCrisisModal();
  }

  // =========================================================================
  // Clinical Knowledge & Crisis Data Binding
  // =========================================================================
  async loadProtocols() {
    try {
      const res = await fetch('/api/protocols');
      const data = await res.json();
      const container = document.getElementById('protocolsList');
      if (!container) return;

      container.innerHTML = data.protocols.map((p) => `
        <div class="protocol-item">
          <h4>${p.title_ar}</h4>
          <span class="protocol-category">${p.evidence_base}</span>
          <ol class="protocol-steps">
            ${p.steps_ar.map((s) => `<li>${s}</li>`).join('')}
          </ol>
        </div>
      `).join('');
    } catch (e) {
      console.error('Failed to load protocols:', e);
    }
  }

  async loadCrisisDirectory() {
    try {
      const res = await fetch('/api/crisis');
      const data = await res.json();
      const container = document.getElementById('crisisList');
      if (!container) return;

      container.innerHTML = data.crisis_directory.map((c) => `
        <div class="crisis-contact-card">
          <strong>${c.organization}</strong>
          <a href="tel:${c.phone_number}" class="phone-link">📞 ${c.display_number}</a>
          <p>${c.description}</p>
          <small style="color:#94a3b8">المحافظات: ${c.jurisdiction} — ${c.availability}</small>
        </div>
      `).join('');
    } catch (e) {
      console.error('Failed to load crisis directory:', e);
    }
  }

  async loadPatientConsent() {
    try {
      const res = await fetch(`/api/patient/${this.patientId}`);
      const data = await res.json();
      const toggle = document.getElementById('consentToggle');
      if (toggle) toggle.checked = data.consent.long_term_memory;
      this.renderMemoriesList(data.memories || []);
    } catch (e) {
      console.error('Failed to load consent:', e);
    }
  }

  async toggleConsent(granted) {
    try {
      await fetch(`/api/patient/${this.patientId}/consent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ granted })
      });
      console.log('[Fadfada] Law 151/2020 consent updated:', granted);
      this.loadPatientConsent();
    } catch (e) {
      console.error('Failed to set consent:', e);
    }
  }

  renderMemoriesList(memories) {
    const list = document.getElementById('patientMemoriesList');
    if (!list) return;

    if (!memories.length) {
      list.innerHTML = '<p class="empty-state">لا توجد ذكريات مسجلة حالياً.</p>';
      return;
    }

    list.innerHTML = memories.map((m) => `
      <div class="memory-row">
        <div>
          <span class="memory-tag">${m.category}</span>
          <p style="font-size:0.85rem; margin-top:0.25rem;">${m.fact_ar}</p>
        </div>
        <button class="erase-btn" onclick="client.eraseMemory('${m.id}')">شطب</button>
      </div>
    `).join('');
  }

  async eraseMemory(memoryId) {
    if (!confirm('هل تريد شطب هذه المعلومة نهائياً وفقاً لحق المحو في القانون 151/2020؟')) return;
    try {
      await fetch(`/api/patient/${this.patientId}/memories/${memoryId}`, { method: 'DELETE' });
      this.loadPatientConsent();
    } catch (e) {
      console.error('Failed to erase memory:', e);
    }
  }
}

// Global UI helper functions and gesture unlocking
let client = null;
window.addEventListener('DOMContentLoaded', () => {
  client = new FadfadaClient();

  // Ensure WebAudio Context is unlocked on any user gesture
  const unlockAudio = () => {
    if (client && client.audioStreamer) {
      client.audioStreamer.initAudioContext();
    }
  };
  document.addEventListener('click', unlockAudio, { passive: true });
  document.addEventListener('touchstart', unlockAudio, { passive: true });
  document.addEventListener('keydown', unlockAudio, { passive: true });
});

function toggleVoiceSession() { client.toggleVoiceSession(); }
function triggerBargeIn() { client.triggerBargeIn(); }
function sendTypedTurn() { client.sendTypedTurn(); }
function handleInputKey(e) { if (e.key === 'Enter') client.sendTypedTurn(); }
function toggleConsent(val) { client.toggleConsent(val); }

function openProtocolsDrawer() { document.getElementById('protocolsDrawer').classList.add('active'); }
function closeProtocolsDrawer() { document.getElementById('protocolsDrawer').classList.remove('active'); }
function openPrivacyModal() { document.getElementById('privacyModal').classList.add('active'); }
function closePrivacyModal() { document.getElementById('privacyModal').classList.remove('active'); }
function openCrisisModal() { document.getElementById('crisisModal').classList.add('active'); }
function closeCrisisModal() { document.getElementById('crisisModal').classList.remove('active'); }
