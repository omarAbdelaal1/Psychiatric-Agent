/**
 * FADFADA (فضفضة) — Master Web Audio & Full-Duplex Live Streaming Client
 * Ported from reference sales_voice_agent_demo architecture:
 * 1. Single locked Aoede voice configuration.
 * 2. Studio-grade AudioStreamer with immediate gain restoration & zero-crop startup.
 * 3. Global user gesture AudioContext unlocking (click, touchstart, keydown).
 * 4. Separated conversational message feed (live streaming active bubbles + 1.5s cadence sealing).
 * 5. Egyptian clinical protocol adherence & Law 151/2020 privacy compliance.
 */

class FadfadaClient {
  constructor() {
    this.socket = null;
    this.isRecording = false;
    this.isPlayingAgentAudio = false;
    this.patientId = 'default_user';
    this.sessionId = 'sess_' + Date.now();
    this.audioGeneration = 0;
    this.isManualInterruptActive = false;

    // Visualizer energy metrics
    this.userRMS = 0;
    this.orbPhase = 0;

    // Active streaming message elements (matching sales_voice_agent_demo architecture)
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
    this.btnFinishTurn = document.getElementById('btnFinishTurn');
    this.btnInterrupt = document.getElementById('btnInterrupt');

    // Instantiate studio-grade AudioStreamer with native full-duplex streaming
    this.audioStreamer = new AudioStreamer({
      onAudioChunk: (base64Audio) => {
        if (this.socket && this.socket.readyState === WebSocket.OPEN && this.isRecording) {
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
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
          this.socket.send(JSON.stringify({
            type: 'playback_state',
            is_playing: isPlaying
          }));
        }
        if (isPlaying) {
          this.setStatus('فضفضة يتحدث..');
        } else {
          this.setStatus(this.isRecording ? 'أنا سامعاك.. اتفضل اتكلم' : 'مستعد للحديث');
        }
      }
    });

    this.initVisualizer();
    this.connectWebSocket();
    this.loadProtocols();
    this.loadCrisisDirectory();
    this.loadPatientConsent();
  }

  // =========================================================================
  // WebSocket Connection & Event Demuxing
  // =========================================================================
  connectWebSocket() {
    const urlParams = new URLSearchParams(window.location.search);
    const customBackend = urlParams.get('backend') || window.FADFADA_BACKEND_URL || localStorage.getItem('fadfada_backend_url');

    let wsUrl;
    if (customBackend) {
      const cleanHost = customBackend.replace(/^https?:\/\//, '').replace(/^wss?:\/\//, '').replace(/\/ws\/live$/, '').replace(/\/$/, '');
      const proto = (customBackend.startsWith('wss://') || customBackend.startsWith('https://') || window.location.protocol === 'https:') ? 'wss:' : 'ws:';
      wsUrl = `${proto}//${cleanHost}/ws/live`;
    } else {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${protocol}//${window.location.host}/ws/live`;
    }
    console.log('[Fadfada] Connecting WebSocket:', wsUrl);

    this.socket = new WebSocket(wsUrl);

    this.socket.onopen = () => {
      console.log('[Fadfada] WebSocket connected.');
      // Voice strictly locked to Aoede
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
        console.error('[Fadfada] Failed to parse message:', err);
      }
    };

    this.socket.onerror = (err) => console.error('[Fadfada] WebSocket error:', err);
    this.socket.onclose = () => {
      console.warn('[Fadfada] WebSocket closed. Reconnecting in 3s..');
      setTimeout(() => this.connectWebSocket(), 3000);
    };
  }

  handleServerMessage(msg) {
    switch (msg.type) {
      case 'ready':
        this.setStatus('مستعد للحديث');
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
        break;

      case 'agent_text':
      case 'model_transcription':
        this.appendAgentText(msg.text);
        break;

      case 'interrupted': {
        const incomingGen = Number(msg.generation_id ?? 0);
        this.audioGeneration = Math.max(this.audioGeneration + 1, incomingGen);
        console.log(`[Fadfada] Interrupted signal received (reason: ${msg.reason}, generation: ${this.audioGeneration})`);
        this.audioStreamer.stopPlayback();
        this.hideInterimCard();

        // Show a human-interruption badge only when user speech/manual input is confirmed
        if (msg.reason === 'manual' || this.isManualInterruptActive) {
          if (this.activeAgentMsgElem && !this.activeAgentMsgElem.querySelector('.interrupted-badge')) {
            const badge = document.createElement('span');
            badge.className = 'interrupted-badge';
            badge.style = 'display:inline-block; font-size:0.75rem; color:#dc2626; background:#fee2e2; padding:1px 6px; border-radius:4px; margin-inline-start:6px;';
            badge.textContent = '[تمت المقاطعة ⚡]';
            this.activeAgentMsgElem.appendChild(badge);
          }
        }
        this.sealActiveAgentBubble();
        this.sealActiveUserBubble();
        this.setStatus('تم إيقاف الرد');
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
        this.setStatus(this.isRecording ? 'أنا سامعاك.. اتفضل اتكلم' : 'مستعد للحديث');
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
  // Separated Dialogue Message Feed Management (Architecture from sales_voice_agent_demo)
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

    // Seal active agent bubble when user speaks
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

    // Automatically seal active user bubble after 1.5s of silence
    if (this.userUtteranceTimer) clearTimeout(this.userUtteranceTimer);
    this.userUtteranceTimer = setTimeout(() => {
      this.sealActiveUserBubble();
    }, 1500);
  }

  appendAgentText(chunk) {
    if (!chunk || !chunk.trim()) return;
    const clean = this.sanitizeASR(chunk);
    if (!clean) return;

    // Seal active user bubble
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
      this.showInterimCard('فضفضة يتحدث الآن...', this.activeAgentMsgElem.textContent);
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
      this.setStatus('أنا سامعاك.. اتفضل اتكلم');
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
    this.setStatus('مستعد للحديث');
    console.log('[Fadfada] Microphone capture stopped');
  }

  triggerTurnComplete() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'audio_turn_complete' }));
      this.setStatus('فضفضة يفكر بالرد..');
    }
  }

  triggerBargeIn() {
    console.log('[Fadfada] Manual interrupt button clicked.');
    this.isManualInterruptActive = true;
    this.audioStreamer.stopPlayback();
    if (this.activeAgentMsgElem && this.activeAgentMsgElem.textContent.trim()) {
      if (!this.activeAgentMsgElem.querySelector('.interrupted-badge')) {
        const badge = document.createElement('span');
        badge.className = 'interrupted-badge';
        badge.style = 'display:inline-block; font-size:0.75rem; color:#dc2626; background:#fee2e2; padding:1px 6px; border-radius:4px; margin-inline-start:6px;';
        badge.textContent = '[تمت المقاطعة ⚡]';
        this.activeAgentMsgElem.appendChild(badge);
      }
    }
    this.sealActiveUserBubble();
    this.sealActiveAgentBubble();
    this.hideInterimCard();
    this.setStatus('أنا سامعاك.. اتفضل اتكلم');
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
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

    // Immediately display user message in conversation feed
    this.addMessage(text, 'user');
    if (input) input.value = '';

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({
        type: 'text',
        text: text
      }));
      this.setStatus('فضفضة يكتب رداً..');
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
        // User speaking: warm vibrant teal/emerald glow
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
        if (this.btnFinishTurn) this.btnFinishTurn.disabled = false;
        if (this.btnInterrupt) this.btnInterrupt.disabled = false;
      } else {
        this.btnStartVoice.classList.remove('recording');
        if (this.btnRecordLabel) this.btnRecordLabel.textContent = 'ابدأ الفضفضة';
        if (this.btnFinishTurn) this.btnFinishTurn.disabled = true;
        if (this.btnInterrupt) this.btnInterrupt.disabled = true;
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

      container.innerHTML = data.protocols.map(p => `
        <div class="protocol-item">
          <h4>${p.title_ar}</h4>
          <span class="protocol-category">${p.evidence_base}</span>
          <ol class="protocol-steps">
            ${p.steps_ar.map(s => `<li>${s}</li>`).join('')}
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

      container.innerHTML = data.crisis_directory.map(c => `
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

    list.innerHTML = memories.map(m => `
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

  // Ensure WebAudio Context is unlocked on any user gesture (matching sales_voice_agent_demo)
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
function triggerTurnComplete() { client.triggerTurnComplete(); }
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
