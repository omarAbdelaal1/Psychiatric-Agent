# Comprehensive Dossier: All Files Involved in Voice Persona Shifts & False Interruption Artifacts

> **Generated for**: Omni-Orchestrator Mode B (Fast Direct Execution)
> **Target System**: Fadfada (فضفضة) AI Psychiatric Voice Companion
> **Root Issues Analyzed**:
> 1. Recurrent false interruptions (`[تمت المقاطعة ⚡]`) occurring during agent speech.
> 2. Voice persona shifts, pitch instability, and repetition of truncated sentence fragments.

---

## Executive Forensic Root-Cause Analysis

### 1. The Physical Acoustic Echo Loop (The Primary Cause of Wrong Interrupts)
In Google Gemini Live API (`BidiGenerateContent`), the model runs **real-time server-side Voice Activity Detection (VAD)** on the incoming audio uplink (`realtimeInput.audio`).
When the agent speaks through the client's physical laptop speakers:
1. Sound waves travel from the laptop speakers through room air into the laptop microphone.
2. Although the browser requests WebRTC `echoCancellation: true`, hardware echo cancellation on Windows laptops is imperfect and leaks acoustic bleed.
3. If `frontend/js/audio-streamer.js` transmits *any* microphone frame containing speaker audio to the server, that frame is forwarded to Gemini Live.
4. Gemini Live hears Arabic speech in its input stream while it is producing output.
5. Gemini Live assumes the user is speaking, emits `{"serverContent": {"interrupted": true}}`, and cuts its own audio stream.
6. The server forwards `{"type": "interrupted"}` to the client, causing `app.js` to append `[تمت المقاطعة ⚡]`.

### 2. Why Voice Personas Shift and Words Are Repeated
When Gemini Live is interrupted by its own acoustic echo, the audio fragment it heard (e.g., 'الله وبركاته' or 'شجرة كبيرة') becomes the new conversational context.
Because Gemini is generating a spontaneous response to an isolated audio snippet rather than a coherent turn:
- It changes its pitch, cadence, and vocal prosody.
- It repeats or continues from the echo fragment (e.g., agent says 'وعليكم السلام ورحمة الله وبركاته...', mic sends 'الله وبركاته', and agent begins next sentence with 'الله وبركاته. منورني النهاردة...').
- If the interruption triggers a reconnect or state reset, persona anchoring can waver.

### 3. The Flawed Silence Injection on `user_interrupt`
In `backend/services/gemini_live_bridge.py`, `handle_user_interrupt()` sends a 10ms PCM silence frame (`\x00` * 320) into `realtimeInput.audio`. In Gemini Live, sending audio input into an active turn can re-trigger Gemini to generate a response to silence!

---

## File Inventory

| # | File Path | Primary Function | Impact on False Interrupts | Impact on Voice Persona |
|---|---|---|---|---|
| 1 | `frontend/js/audio-streamer.js` | Web Audio DSP, mic capture, barge-in | **CRITICAL** (determines which mic frames reach Gemini) | High (sends echo fragments that destabilize voice) |
| 2 | `frontend/js/app.js` | Client UI & WebSocket coordinator | **CRITICAL** (renders interrupt badges, sends user_interrupt) | Medium (initiates turn reset) |
| 3 | `backend/services/gemini_live_bridge.py` | Gemini Live Bidi WebSocket bridge | **CRITICAL** (handles interrupted signal, sends silence frame) | **CRITICAL** (sets voiceConfig, model setup) |
| 4 | `backend/app.py` | FastAPI gateway & message router | High (routes audio & interruption events) | Low |
| 5 | `backend/config.py` | Global audio specs & voice defaults | Medium (defines default voice Aoede & sample rates) | High (voice configuration) |
| 6 | `prompts/live_agent/system_prompt.md` | System instruction & persona prompt | Low | **CRITICAL** (enforces female Egyptian persona & prevents drift) |
| 7 | `backend/services/psychiatric_tools.py` | Clinical function calling declarations | Medium (tool execution can pause speech) | Low |
| 8 | `frontend/index.html` | HTML layout & script inclusion order | Low (script dependencies) | Low |
| 9 | `run.py` | Production launcher & environment setup | Low (runtime environment) | Low |

---

## 1. frontend/js/audio-streamer.js
**Path**: `frontend/js/audio-streamer.js`  
**Role**: Client-Side Web Audio DSP, Microphone Capture, Adaptive Barge-In, and Playback Queue  
**Forensic Impact**: Directly captures microphone audio and detects barge-in. Contains the thresholding logic, AGC settings, and playback state tracking. When speaker sound leaks into the mic, this file either falsely triggers barge-in or leaks echo frames to the backend, causing Gemini to interrupt itself.  

```javascript
/**
 * AudioStreamer - Voice AI Real-Time Streaming Audio Engine (Fadfada فضفضة)
 * Studio-Grade Audio Pipeline ported from sales_voice_agent_demo:
 * 1. Single AudioContext Architecture: Eliminates WASAPI clock drift, buffer underruns, and dual-context hardware contention.
 * 2. Native Sample Rate Upsampling: Upsamples 24kHz Gemini PCM to AudioContext's native sample rate (48kHz/44.1kHz)
 *    in JS with linear interpolation. Bypasses Web Audio's internal sinc edge-zeroing resampler, eliminating 20-50Hz Dirac comb buzzing.
 * 3. Boundary Micro-Blending: Smoothly interpolates the first 16 samples with the previous chunk's end sample,
 *    guaranteeing zero DC step discontinuities or click artifacts.
 * 4. Micro-Chunk Accumulator: Gathers small fragments (<240 samples, like Gemini's initial 2-byte chunk)
 *    before scheduling, preventing 0ms buffer source collapses.
 * 5. Adaptive Low-Latency Jitter Buffer: 40ms smooth initial buffer, with 15ms micro-bridges on transient under-runs.
 * 6. Debounced Playback State: Prevents avatar animation jitter and premature turn resets between speech pauses.
 * 7. Isolated Single-Bus Mic Capture: ScriptProcessor connected via 0.0 gain node to prevent speaker bleed and ground-loop feedback hum.
 * 8. Immediate Gain Restoration: Ensures 100% gain on the very first sample so speech starts without cropping or latency.
 */

class AudioStreamer {
  constructor(options = {}) {
    this.onAudioChunk = options.onAudioChunk || (() => {});
    this.onMicLevel = options.onMicLevel || (() => {});
    this.onPlaybackStateChange = options.onPlaybackStateChange || (() => {});
    this.onSpeechEnd = options.onSpeechEnd || (() => {});
    this.onBargeIn = options.onBargeIn || (() => {});

    // User Speech Cadence Detection & VAD Thresholds
    this.isUserSpeaking = false;
    this.userSpeechTimer = null;
    this.SILENCE_TURN_THRESHOLD_MS = 1600; // Natural conversational cadence without premature cutoffs
    this.NORMAL_VAD_RMS_THRESHOLD = 0.018;
    this.BARGE_IN_REQUIRED_FRAMES = 4;     // ~170ms: sustained human utterance; prevents single-spike false interrupts
    this.bargeInConsecutiveFrames = 0;

    // Shared AudioContext
    this.audioContext = null;

    // Microphone Capture Nodes
    this.mediaStream = null;
    this.scriptProcessor = null;
    this.inputSource = null;
    this.inputAnalyser = null;
    this.muteGain = null;

    // Playback Nodes
    this.outputGain = null;
    this.highPassFilter = null;
    this.outputAnalyser = null;

    // Playback State & Scheduling
    this.isPlaying = false;
    this.nextScheduledTime = 0;
    this.activeSources = [];
    this.isMuted = false;
    this.leftoverByte = null;
    this.sampleAccumulator = [];
    this.lastChunkEndSample = null;
    this.endDebounceTimer = null;

    this.TARGET_IN_RATE = 16000;
    this.TARGET_OUT_RATE = 24000;
    this.MIN_CHUNK_SAMPLES = 240; // 10ms at 24kHz
  }

  /**
   * Initializes or returns the master AudioContext.
   */
  initAudioContext() {
    if (!this.audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx();

      // Master Output Gain Node (0.85 provides crystal-clear audio while preventing speaker clipping)
      this.outputGain = this.audioContext.createGain();
      this.outputGain.gain.setValueAtTime(0.85, this.audioContext.currentTime);

      // Clean Sub-bass Rumble / DC Filter (Gentle high-pass at 70Hz)
      this.highPassFilter = this.audioContext.createBiquadFilter();
      this.highPassFilter.type = 'highpass';
      this.highPassFilter.frequency.setValueAtTime(70, this.audioContext.currentTime);
      this.highPassFilter.Q.setValueAtTime(0.707, this.audioContext.currentTime);

      // Visualizer Tap Analyser (Tap ONLY - never connected directly to destination)
      this.outputAnalyser = this.audioContext.createAnalyser();
      this.outputAnalyser.fftSize = 256;
      this.outputAnalyser.smoothingTimeConstant = 0.8;

      // Clean signal path: source -> outputGain -> highPassFilter -> destination
      //                                   └───> outputAnalyser (read-only)
      this.outputGain.connect(this.highPassFilter);
      this.highPassFilter.connect(this.audioContext.destination);
      this.outputGain.connect(this.outputAnalyser);
    }

    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume().catch((e) => {
        console.warn('Could not resume AudioContext immediately:', e);
      });
    }

    return this.audioContext;
  }

  /**
   * High-quality linear resampling between sample rates for Float32Array.
   */
  resampleFloat32(input, srcRate, dstRate) {
    if (srcRate === dstRate || input.length === 0) return input;
    const ratio = srcRate / dstRate;
    const outLength = Math.round(input.length / ratio);
    const output = new Float32Array(outLength);

    for (let i = 0; i < outLength; i++) {
      const srcPos = i * ratio;
      const index = Math.floor(srcPos);
      const frac = srcPos - index;

      const s0 = input[index] || 0;
      const s1 = (index + 1 < input.length) ? input[index + 1] : s0;

      output[i] = s0 + frac * (s1 - s0);
    }

    return output;
  }

  /**
   * Downsamples microphone audio buffer from srcRate to dstRate using averaging.
   */
  downsampleBuffer(inputBuffer, srcRate, dstRate) {
    if (srcRate === dstRate) return inputBuffer;
    const ratio = srcRate / dstRate;
    const newLength = Math.round(inputBuffer.length / ratio);
    const result = new Float32Array(newLength);
    let offsetResult = 0;
    let offsetInput = 0;

    while (offsetResult < result.length) {
      const nextOffsetInput = Math.round((offsetResult + 1) * ratio);
      let accum = 0;
      let count = 0;
      for (let i = offsetInput; i < nextOffsetInput && i < inputBuffer.length; i++) {
        accum += inputBuffer[i];
        count++;
      }
      result[offsetResult] = count > 0 ? accum / count : inputBuffer[offsetInput];
      offsetResult++;
      offsetInput = nextOffsetInput;
    }
    return result;
  }

  /**
   * Start capturing microphone audio and streaming 16kHz PCM.
   * Uses single shared AudioContext with isolated mute gain to prevent feedback.
   */
  async startRecording() {
    this.initAudioContext();
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true // Enable AGC so Chrome WebRTC AEC3 reference leveling prevents mic saturation
        }
      });

      const hardwareSampleRate = this.audioContext.sampleRate;
      console.log(`[AudioStreamer] Microphone opened via shared AudioContext at ${hardwareSampleRate} Hz`);

      this.inputSource = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.inputAnalyser = this.audioContext.createAnalyser();
      this.inputAnalyser.fftSize = 256;
      this.inputSource.connect(this.inputAnalyser);

      // Buffer size 2048 gives ~42.6ms chunks at 48kHz
      this.scriptProcessor = this.audioContext.createScriptProcessor(2048, 1, 1);

      this.scriptProcessor.onaudioprocess = (e) => {
        const rawData = e.inputBuffer.getChannelData(0);

        // Guarantee 100% silent output buffer
        const outData = e.outputBuffer.getChannelData(0);
        outData.fill(0);

        // Calculate RMS volume level for UI meter
        let sum = 0;
        for (let i = 0; i < rawData.length; i++) {
          sum += rawData[i] * rawData[i];
        }
        const rms = Math.sqrt(sum / rawData.length);
        this.onMicLevel(Math.min(1, rms * 6));

        // Adaptive Dual-Energy Echo-Aware Barge-In Detection:
        // Evaluates output speaker energy in real time to distinguish true user speech from speaker acoustic bleed
        if (this.isPlaying) {
          let outputRMS = 0;
          if (this.outputAnalyser) {
            const outFreq = new Uint8Array(this.outputAnalyser.frequencyBinCount);
            this.outputAnalyser.getByteFrequencyData(outFreq);
            let outSum = 0;
            for (let i = 0; i < outFreq.length; i++) {
              outSum += outFreq[i];
            }
            outputRMS = outSum / (outFreq.length * 255.0);
          }

          // Dynamic Threshold:
          // - When agent pauses between words (outputRMS == 0): drops to 0.035 for effortless conversational interruption
          // - When agent speaks loudly (outputRMS == 0.4): rises to 0.19, mathematically preventing speaker bleed from self-interrupting
          const dynamicThreshold = Math.max(0.035, outputRMS * 0.40 + 0.030);

          if (rms > dynamicThreshold) {
            this.bargeInConsecutiveFrames++;
            if (this.bargeInConsecutiveFrames >= this.BARGE_IN_REQUIRED_FRAMES) {
              console.log(`[AudioStreamer] Genuine user barge-in detected (Mic RMS: ${rms.toFixed(3)}, Out: ${outputRMS.toFixed(3)}). Halting playback.`);
              this.stopPlayback();
              this.bargeInConsecutiveFrames = 0;
              if (this.onBargeIn) {
                this.onBargeIn();
              }
              // CRITICAL: Drop this frame immediately so speaker bleed tail NEVER leaks to Gemini
              return;
            } else {
              return; // Awaiting confirmation frames to avoid single-spike noise triggers
            }
          } else {
            this.bargeInConsecutiveFrames = 0;
            return; // Cleanly suppress speaker bleed from reaching Gemini while agent is speaking
          }
        } else {
          this.bargeInConsecutiveFrames = 0;
        }

        // User speech cadence detection & silence turn completion trigger
        if (rms > this.NORMAL_VAD_RMS_THRESHOLD) {
          if (!this.isUserSpeaking) {
            this.isUserSpeaking = true;
          }
          if (this.userSpeechTimer) {
            clearTimeout(this.userSpeechTimer);
            this.userSpeechTimer = null;
          }
          this.userSpeechTimer = setTimeout(() => {
            if (this.isUserSpeaking) {
              this.isUserSpeaking = false;
              this.onSpeechEnd();
            }
          }, this.SILENCE_TURN_THRESHOLD_MS);
        }

        // Downsample to 16,000 Hz if hardware rate differs
        const resampledData = this.downsampleBuffer(rawData, hardwareSampleRate, this.TARGET_IN_RATE);

        // Convert Float32Array [-1.0, 1.0] to Int16Array [-32768, 32767]
        const pcm16 = new Int16Array(resampledData.length);
        for (let i = 0; i < resampledData.length; i++) {
          let s = Math.max(-1, Math.min(1, resampledData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        // Encode to Base64
        const uint8 = new Uint8Array(pcm16.buffer);
        let binary = '';
        for (let i = 0; i < uint8.byteLength; i++) {
          binary += String.fromCharCode(uint8[i]);
        }
        const base64Audio = btoa(binary);

        this.onAudioChunk(base64Audio);
      };

      // Mute gain node guarantees 0.0 microphone audio leaks to physical speakers
      this.muteGain = this.audioContext.createGain();
      this.muteGain.gain.setValueAtTime(0.0, this.audioContext.currentTime);

      this.inputSource.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.muteGain);
      this.muteGain.connect(this.audioContext.destination);

      return true;
    } catch (err) {
      console.error('[AudioStreamer] Failed to access microphone:', err);
      throw err;
    }
  }

  /**
   * Stop capturing microphone audio.
   */
  stopRecording() {
    if (this.userSpeechTimer) {
      clearTimeout(this.userSpeechTimer);
      this.userSpeechTimer = null;
    }
    this.isUserSpeaking = false;

    if (this.scriptProcessor) {
      try { this.scriptProcessor.disconnect(); } catch (e) {}
      this.scriptProcessor = null;
    }
    if (this.muteGain) {
      try { this.muteGain.disconnect(); } catch (e) {}
      this.muteGain = null;
    }
    if (this.inputSource) {
      try { this.inputSource.disconnect(); } catch (e) {}
      this.inputSource = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    this.onMicLevel(0);
  }

  /**
   * Queue and play incoming 24kHz PCM audio chunk from Gemini with:
   * - Native sample-rate upsampling (eliminates Web Audio filter edge buzzing)
   * - Continuous boundary micro-blending
   * - Micro-chunk accumulation (guards against 1-sample 2-byte bursts)
   * - Smooth jitter buffer scheduling
   * - Immediate full gain un-ducking (guarantees zero cropping on initial syllables)
   */
  playAudioChunk(base64Data) {
    if (this.isMuted) return;
    this.initAudioContext();

    try {
      // 1. Immediately restore full volume so no initial chunk plays at gain 0
      if (this.outputGain && this.audioContext) {
        const nowGain = this.audioContext.currentTime;
        this.outputGain.gain.cancelScheduledValues(nowGain);
        this.outputGain.gain.setValueAtTime(0.85, nowGain);
      }

      // 2. Decode Base64 string to raw binary bytes
      const binary = atob(base64Data);
      const newBytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        newBytes[i] = binary.charCodeAt(i);
      }

      // 3. Prepend leftover trailing byte from previous chunk if it was split across frames
      let totalBytes;
      if (this.leftoverByte !== null) {
        totalBytes = new Uint8Array(newBytes.length + 1);
        totalBytes[0] = this.leftoverByte;
        totalBytes.set(newBytes, 1);
        this.leftoverByte = null;
      } else {
        totalBytes = newBytes;
      }

      // 4. Ensure strict 16-bit alignment (2 bytes per sample)
      const remainder = totalBytes.length % 2;
      let validLength = totalBytes.length;
      if (remainder !== 0) {
        this.leftoverByte = totalBytes[totalBytes.length - 1];
        validLength = totalBytes.length - 1;
      }

      const numSamples = validLength / 2;
      if (numSamples === 0) return;

      // 5. Convert Little-Endian Int16 to Float32 [-1.0, 1.0]
      const float32 = new Float32Array(numSamples);
      const dataView = new DataView(totalBytes.buffer, totalBytes.byteOffset, validLength);
      for (let i = 0; i < numSamples; i++) {
        const int16 = dataView.getInt16(i * 2, true); // Little-Endian
        float32[i] = int16 < 0 ? int16 / 32768.0 : int16 / 32767.0;
      }

      // 6. Accumulate samples to avoid scheduling microscopic buffers (< 10ms)
      for (let i = 0; i < float32.length; i++) {
        this.sampleAccumulator.push(float32[i]);
      }

      if (this.sampleAccumulator.length < this.MIN_CHUNK_SAMPLES) {
        return; // Wait for enough samples to form a smooth audio buffer
      }

      const rawChunk = new Float32Array(this.sampleAccumulator);
      this.sampleAccumulator = [];

      // 7. Upsample from Gemini's 24kHz to AudioContext's native rate (e.g. 48kHz)
      const nativeRate = this.audioContext.sampleRate;
      const upsampled = this.resampleFloat32(rawChunk, this.TARGET_OUT_RATE, nativeRate);

      // 8. Continuous Boundary Micro-Blending:
      if (!this.isPlaying) {
        // Initial speech turn lead-in de-click (32 samples = ~0.7ms)
        const leadLen = Math.min(32, upsampled.length);
        for (let i = 0; i < leadLen; i++) {
          upsampled[i] *= (i / leadLen);
        }
      } else if (this.lastChunkEndSample !== null && upsampled.length >= 16) {
        // Micro-crossfade chunk boundary to preserve continuous waveform
        for (let i = 0; i < 16; i++) {
          const w = i / 16;
          upsampled[i] = this.lastChunkEndSample * (1 - w) + upsampled[i] * w;
        }
      }
      this.lastChunkEndSample = upsampled[upsampled.length - 1];

      // 9. Create AudioBuffer matching exact native sampleRate
      const audioBuffer = this.audioContext.createBuffer(1, upsampled.length, nativeRate);
      audioBuffer.getChannelData(0).set(upsampled);

      const source = this.audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.outputGain);

      // 10. Low-latency jitter buffer scheduling (exact reference constants)
      const now = this.audioContext.currentTime;
      if (this.nextScheduledTime < now) {
        if (!this.isPlaying) {
          // Fresh speech turn: 40ms low-latency jitter absorption buffer
          this.nextScheduledTime = now + 0.04;
        } else {
          // Transient network hiccup during active speech: bridge smoothly with 15ms lead-in
          this.nextScheduledTime = now + 0.015;
        }
      }

      source.start(this.nextScheduledTime);
      this.activeSources.push(source);
      this.nextScheduledTime += audioBuffer.duration;

      // Clear any pending turn-end debounce
      if (this.endDebounceTimer) {
        clearTimeout(this.endDebounceTimer);
        this.endDebounceTimer = null;
      }

      if (!this.isPlaying) {
        this.isPlaying = true;
        this.onPlaybackStateChange(true);
      }

      source.onended = () => {
        const idx = this.activeSources.indexOf(source);
        if (idx > -1) this.activeSources.splice(idx, 1);

        if (this.activeSources.length === 0) {
          // Debounce turn end by 140ms to prevent visual jitter between speech sentences
          if (this.endDebounceTimer) clearTimeout(this.endDebounceTimer);
          this.endDebounceTimer = setTimeout(() => {
            if (this.activeSources.length === 0) {
              this.isPlaying = false;
              this.lastChunkEndSample = null;
              this.onPlaybackStateChange(false);
            }
          }, 140);
        }
      };
    } catch (err) {
      console.error('[AudioStreamer] Failed to play audio chunk:', err);
    }
  }

  /**
   * Immediate interruption / barge-in: smoothly flush active audio queue.
   */
  stopPlayback() {
    this.leftoverByte = null;
    this.sampleAccumulator = [];
    this.lastChunkEndSample = null;

    if (this.endDebounceTimer) {
      clearTimeout(this.endDebounceTimer);
      this.endDebounceTimer = null;
    }

    // Quick 15ms ramp down gain to avoid sudden pop on interruption
    if (this.outputGain && this.audioContext) {
      try {
        const now = this.audioContext.currentTime;
        this.outputGain.gain.cancelScheduledValues(now);
        this.outputGain.gain.setValueAtTime(this.outputGain.gain.value, now);
        this.outputGain.gain.linearRampToValueAtTime(0, now + 0.015);
        setTimeout(() => {
          if (this.outputGain && this.audioContext) {
            this.outputGain.gain.setValueAtTime(0.85, this.audioContext.currentTime);
          }
        }, 20);
      } catch (e) {}
    }

    this.activeSources.forEach((s) => {
      try {
        s.stop();
        s.disconnect();
      } catch (e) {}
    });
    this.activeSources = [];

    if (this.audioContext) {
      this.nextScheduledTime = this.audioContext.currentTime;
    }
    this.isPlaying = false;
    this.onPlaybackStateChange(false);
  }

  setMute(mute) {
    this.isMuted = mute;
    if (mute) this.stopPlayback();
  }

  /**
   * Returns current audio visualizer frequency byte data.
   */
  getVisualizerData() {
    const data = new Uint8Array(64);
    if (this.isPlaying && this.outputAnalyser) {
      this.outputAnalyser.getByteFrequencyData(data);
    } else if (this.inputAnalyser) {
      this.inputAnalyser.getByteFrequencyData(data);
    }
    return data;
  }
}

window.AudioStreamer = AudioStreamer;

```

---

## 2. frontend/js/app.js
**Path**: `frontend/js/app.js`  
**Role**: Client WebSocket Application Controller & Interruption Event Handler  
**Forensic Impact**: Coordinates the WebSocket connection, listens for 'interrupted' messages from the server, stamps the '[تمت المقاطعة ⚡]' badge into the dialogue bubble, triggers 'user_interrupt' messages, and manages conversational turn sealing.  

```javascript
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

    // Instantiate studio-grade AudioStreamer with adaptive echo-aware barge-in
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
      },
      onSpeechEnd: () => {
        console.log('[Fadfada] Natural speech cadence detected (1600ms). Triggering turnComplete.');
        this.triggerTurnComplete();
      },
      onBargeIn: () => {
        console.log('[Fadfada] User genuine voice barge-in detected.');
        this.triggerBargeIn();
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
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;
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

      case 'audio':
        this.sealActiveUserBubble();
        if (msg.data) {
          this.audioStreamer.playAudioChunk(msg.data);
        }
        break;

      case 'user_transcription':
      case 'user_text':
        this.appendUserTranscription(msg.text);
        break;

      case 'agent_text':
      case 'model_transcription':
        this.appendAgentText(msg.text);
        break;

      case 'interrupted':
        console.log('[Fadfada] Interrupted / Barge-in');
        this.audioStreamer.stopPlayback();
        if (this.activeAgentMsgElem) {
          const badge = document.createElement('span');
          badge.className = 'interrupted-badge';
          badge.style = 'display:inline-block; font-size:0.75rem; color:#dc2626; background:#fee2e2; padding:1px 6px; border-radius:4px; margin-inline-start:6px;';
          badge.textContent = '[تمت المقاطعة ⚡]';
          this.activeAgentMsgElem.appendChild(badge);
        }
        this.sealActiveAgentBubble();
        this.sealActiveUserBubble();
        this.hideInterimCard();
        this.setStatus('تمت المقاطعة');
        break;

      case 'turn_complete':
        this.sealActiveUserBubble();
        this.sealActiveAgentBubble();
        this.hideInterimCard();
        this.setStatus(this.isRecording ? 'أنا سامعاك.. اتفضل اتكلم' : 'مستعد للحديث');
        break;

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

    const trimmedChunk = chunk;
    const lastChar = existing.slice(-1);
    const firstChar = trimmedChunk.charAt(0);

    const attachedPunctuation = new Set(['.', '،', '؟', '!', ',', '?', ':', ';', '؛', ')', ']', '}', '»', '”']);

    if (attachedPunctuation.has(firstChar)) {
      return existing.trimEnd() + trimmedChunk;
    }

    if (/\s/.test(lastChar) || /\s/.test(firstChar)) {
      return existing + trimmedChunk;
    }

    return existing + ' ' + trimmedChunk;
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
    console.log('[Fadfada] User interrupt / barge-in triggered.');
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

```

---

## 3. backend/services/gemini_live_bridge.py
**Path**: `backend/services/gemini_live_bridge.py`  
**Role**: Backend Gemini Live BidiGenerateContent WebSocket Bridge  
**Forensic Impact**: Establishes full-duplex session with Gemini Live API. Configures voiceName ('Aoede') and systemInstruction. Forwards microphone PCM chunks to Gemini, listens for serverContent.interrupted, and injects silence PCM frames upon user_interrupt (which can inadvertently re-trigger Gemini generation).  

```python
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
    ):
        self.session_id = session_id
        self.patient_id = patient_id
        self.knowledge_service = knowledge_service
        self.send_to_client = send_to_client
        # Strictly lock voice to single permanent Aoede voice
        self.voice = config.DEFAULT_VOICE

        self.gemini_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_reconnecting = False
        self.is_closed = False

        # Turn transcript tracking
        self.current_user_text = ""
        self.current_agent_text = ""

        # Load Egyptian Colloquial system prompt
        self.system_prompt_text = (
            "أنت 'فضفضة' (Fadfada) — رفيق استماع داعم ومريح نفسياً يتحدث بالعامية المصرية المعاصرة، الهادئة والدافئة.\n"
            "- تحدث بالعامية المصرية فقط.\n"
            "- سؤال واحد فقط في كل مرة.\n"
            "- لا تقدم أي تشخيصات طبية ولا تصف أي أدوية مطلقاً.\n"
            "- في حالات الخطر أو الانتحار، استخدم أداة escalate_crisis وانصح فوراً بالاتصال بالخط الساخن 16328 أو الإسعاف 123.\n"
            "- عند القلق المفرط أو تسارع الأنفاس، استخدم أداة trigger_grounding_exercise لمشاركة تمرين التنفس المربع 4-4-4."
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
                    "parts": [{"text": self.system_prompt_text}]
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
        """Signals turn completion when user finishes speaking."""
        if not self.gemini_ws or not self.is_connected:
            return

        try:
            await self.gemini_ws.send(json.dumps({
                "clientContent": {
                    "turnComplete": True
                }
            }))
        except Exception as e:
            logger.warning(f"Failed to send turnComplete to Gemini: {e}")

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
        """Handles barge-in interruption from user."""
        logger.info(f"User interrupted session {self.session_id}")
        self.current_agent_text = ""
        if self.gemini_ws and self.is_connected:
            try:
                # Send 10ms silence frame (160 samples = 320 bytes) to instruct Gemini Live to halt output
                silence_pcm = base64.b64encode(b"\x00" * 320).decode("utf-8")
                await self.gemini_ws.send(json.dumps({
                    "realtimeInput": {
                        "audio": {
                            "mimeType": "audio/pcm;rate=16000",
                            "data": silence_pcm
                        }
                    }
                }))
            except Exception as e:
                logger.debug(f"Failed to signal interrupt to Gemini: {e}")
        # Notify client to immediately silence speakers
        await self.send_to_client({"type": "interrupted"})

    async def gemini_listen_loop(self, on_turn_complete_callback: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None) -> None:
        """Continuous loop reading responses from Gemini Live and streaming to client."""
        while not self.is_closed:
            if not self.gemini_ws or not self.is_connected:
                await asyncio.sleep(0.2)
                continue

            try:
                raw_response = await self.gemini_ws.recv()
            except websockets.exceptions.ConnectionClosed:
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
                    # 1. User transcription chunk (from Gemini's internal STT)
                    in_trans = server_content.get("inputTranscription") or resp_json.get("inputTranscription")
                    if in_trans and isinstance(in_trans, dict):
                        user_chunk = in_trans.get("text", "")
                        if user_chunk:
                            self.current_user_text = append_with_whitespace(self.current_user_text, user_chunk)
                            await self.send_to_client({
                                "type": "user_transcription",
                                "text": user_chunk,
                            })
                            # Real-time crisis detection on user spoken words
                            crisis_check = self.knowledge_service.detect_crisis_signal(user_chunk)
                            if crisis_check["is_crisis"]:
                                await self.send_to_client({
                                    "type": "crisis_alert",
                                    "details": crisis_check,
                                    "primary_hotline": "16328",
                                    "ambulance": "123",
                                })

                    # 2. Agent output transcription chunk
                    out_trans = server_content.get("outputTranscription") or resp_json.get("outputTranscription")
                    if out_trans and isinstance(out_trans, dict):
                        agent_chunk = out_trans.get("text", "")
                        if agent_chunk:
                            self.current_agent_text = append_with_whitespace(self.current_agent_text, agent_chunk)
                            await self.send_to_client({
                                "type": "agent_text",
                                "text": agent_chunk,
                            })

                    # 3. Model Audio Parts (24kHz PCM Little-Endian mono)
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
                                    })
                            if "text" in part and not out_trans:
                                text_chunk = part.get("text", "")
                                if text_chunk:
                                    self.current_agent_text = append_with_whitespace(self.current_agent_text, text_chunk)
                                    await self.send_to_client({
                                        "type": "agent_text",
                                        "text": text_chunk,
                                    })

                    # 4. Turn / Generation Complete
                    if server_content.get("turnComplete") or server_content.get("generationComplete"):
                        user_final = self.current_user_text.strip()
                        agent_final = self.current_agent_text.strip()
                        if on_turn_complete_callback and (user_final or agent_final):
                            await on_turn_complete_callback(user_final, agent_final)

                        self.current_user_text = ""
                        self.current_agent_text = ""
                        await self.send_to_client({"type": "turn_complete"})

                    # 5. Interrupted (Barge-in detected by Gemini)
                    if server_content.get("interrupted"):
                        self.current_agent_text = ""
                        await self.send_to_client({"type": "interrupted"})

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

```

---

## 4. backend/app.py
**Path**: `backend/app.py`  
**Role**: FastAPI Application & Live WebSocket Gateway (/ws/live)  
**Forensic Impact**: Serves the /ws/live WebSocket endpoint and routes incoming client messages (audio, user_interrupt, audio_turn_complete, playback_state) to the Gemini Live bridge. Manages session lifecycle and concurrent async tasks.  

```python
"""
FastAPI Application & Live Streaming Gateway for Fadfada Psychiatric Agent.
Implements AppSec middleware, REST APIs, and full-duplex WebSocket gateway.
"""

import asyncio
import json
import logging
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
from backend.storage import SimpleStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fadfada.app")

# Initialize core services
storage = SimpleStorage(config.DATABASE_PATH)
knowledge_service = KnowledgeService()
memory_service = MemoryService(storage)

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
    result = await memory_service.extract_and_reconcile(
        patient_id=payload.patient_id,
        session_id=session_id,
    )
    return result


@app.post("/api/session/{session_id}/recap")
async def generate_session_recap(session_id: str):
    session = await storage.get_session(session_id)
    messages = await storage.get_messages(session_id)

    if not messages:
        recap_text = "شكراً لمشاركتك اليوم في فضفضة. نتمنى لك يوماً هادئاً، ونحن هنا دائماً متى أردت التحدث."
    else:
        recap_text = (
            "جلسة اليوم كانت مساحة آمنة عبرت فيها عن اللي في قلبك بكل صدق. "
            "اتكلمنا عن أهمية أخذ فترات راحة قصيرة لما الضغط يزيد، وممارسة تمرين التنفس المربع لما تحس بضربات قلبك سريعة. "
            "افتكر إن خطوة واحدة صغيرة النهاردة كافية جداً، وسلامتك النفسية دايماً هي الأولوية. "
            "لو حسيت بأي وقت إن الحمل أكبر منك، الخط الساخن للصحة النفسية 16328 متاح 24 ساعة."
        )

    return {
        "session_id": session_id,
        "recap_ar": recap_text,
        "turns_count": len(messages),
    }


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

        # Initialize bridge
        bridge = GeminiLiveBridge(
            session_id=session_id,
            patient_id=patient_id,
            knowledge_service=knowledge_service,
            send_to_client=send_to_client,
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

```

---

## 5. backend/config.py
**Path**: `backend/config.py`  
**Role**: Configuration, Audio Constants, and Model Settings  
**Forensic Impact**: Defines the model (gemini-3.8-live), voice name (Aoede), uplink sample rate (16kHz), downlink sample rate (24kHz), VAD thresholds, and the Gemini API key failover pool.  

```python
"""
Configuration and audio constants for Fadfada Psychiatric Agent.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Server Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8005"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# API Keys (Supports primary and fallback pool from sales_voice_agent_demo)
GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY")
    or "YOUR_GEMINI_API_KEY_HERE"
)
GEMINI_API_KEYS = [
    k for k in [
        os.getenv("GEMINI_API_KEY"),
        "YOUR_GEMINI_API_KEY_HERE",
        "YOUR_BACKUP_GEMINI_API_KEY_HERE",
    ] if k
]

# AI Models (Verified active with BidiGenerateContent on Google Gemini Live API)
MODEL_LIVE = os.getenv("MODEL_LIVE", "gemini-3.8-live")
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-3.8-flash")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "Aoede")

# Gemini Live WebSocket Endpoint
GEMINI_WS_URL = (
    f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
)

# Audio Pipeline Specifications (Adhering to PIPELINE_DOCUMENTATION.md Section 3)
AUDIO_INPUT_SAMPLE_RATE = 16000     # 16kHz PCM mono uplink from client
AUDIO_OUTPUT_SAMPLE_RATE = 24000    # 24kHz PCM mono downlink from model
AUDIO_CHANNELS = 1                  # Mono
AUDIO_SAMPLE_WIDTH = 2              # 16-bit PCM (2 bytes per sample)
AUDIO_CHUNK_SAMPLES = 1600          # 100ms frame at 16kHz
AUDIO_CHUNK_BYTES = AUDIO_CHUNK_SAMPLES * AUDIO_SAMPLE_WIDTH  # 3200 bytes

# VAD and Turn Timing (Studio-grade debounced cadence)
VAD_SILENCE_TIMEOUT_MS = 1600       # 1600ms silence hangtime for natural clinical pauses
VAD_ENERGY_THRESHOLD = 0.018        # RMS energy threshold for speech

# Storage
DATABASE_PATH = BASE_DIR / "fadfada.db"

```

---

## 6. prompts/live_agent/system_prompt.md
**Path**: `prompts/live_agent/system_prompt.md`  
**Role**: Live Agent System Prompt & Multimodal Persona Anchor  
**Forensic Impact**: Anchors Fadfada's personality, Egyptian Colloquial Arabic dialect, female gender, and tone. If Gemini is interrupted by acoustic echo fragments, weak prompt constraints cause the model to shift prosody, pitch, or accent.  

```markdown
# هويتك الشخصية والمهنية ودورك:
أنتِ "فضفضة" (Fadfada) — رفيقة استماع داعمة ومريحة نفسياً تتحدثين في جلسة صوتية حية بالعامية المصرية المعاصرة، الهادئة والدافئة (Gemini 3.8 Live).
اسمكِ: فضفضة (Fadfada).
جنسكِ وصيغتكِ اللغوية: أنثى (تحدثي دائماً بصيغة المؤنث لنفسك: أنا سامعاك، متفهمة، حاسة بيك، هكون معاك خطوة بخطوة، يسعدني أسمعك).
بلدك ولهجتك الأصلية: جمهورية مصر العربية (لهجة عامية مصرية قاهرية بيضاء دافئة ومهذبة 100%).
صوتكِ المعتمد الوحيد: Aoede (صوت نسائي دافئ هادئ ومريح). ممنوع منعاً باتاً تغيير الصوت أو النبرة أو جنس المتحدث أو استخدام أي صوت رجالي نهائياً طوال المحادثة!
دورك: الاستماع النشط، التفريغ العاطفي، مساعدة المستخدم على التعبير عن مشاعره، واقتراح أساليب التأقلم والتهدئة المعتمدة سريرياً.

# قواعد اللهجة المصرية وأسلوب الحديث الصوتي:
- تحدثي دائماً بالعامية المصرية المعاصرة المريحة: "ألف سلامة عليك"، "فضفض وطلع اللي في قلبك"، "أنا سامعاك ومقدّرة اللي بتمر بيه"، "ولا تشيل هم"، "خطوة بخطوة".
- ❌ ممنوع التحدث باللغة العربية الفصحى المتكلفة أو أي لهجات أخرى.
- ❌ ممنوع الاستطراد في كلام طويل أو إلقاء محاضرات؛ جملك الصوتية قصيرة، مركزة، ودافئة (جملة أو جملتين فقط في كل مرة).
- اطرحي سؤالاً واحداً فقط في كل مرة، واتركي مساحة للمستخدم ليتحدث ويعبر براحته.
- تجنبي العبارات المصطنعة مثل "أنا عارفة بالظبط حاسس بإيه"؛ بل استمعي وتأكدي من فهمك.

# الحدود والضوابط السريرية والقانونية (وفقاً للقانون 151 لسنة 2020):
1. لستِ طبيبة نفسية ولا تقدمين أي تشخيصات طبية، ولا تصفين أو تعدلين أي أدوية على الإطلاق.
2. لا تدّعي أن هذه الجلسة بديل عن الطبيب البشري المؤهل أو الطوارئ الطبية.
3. خصوصية المريض وبياناته مقدسة ومحمية وفق القانون المصري 151/2020؛ احترمي رغبة المريض دائماً وحقه في الخصوصية وحذف بياناته.

# بروتوكول الأمان والطوارئ النفسية الفوري:
- في حالات الخطر الشديد، إيذاء النفس، أو التفكير في الانتحار:
  1. توقفي فوراً عن تقديم أي نصائح عادية.
  2. استخدمي أداة `escalate_crisis`.
  3. انصحي بهدوء وثبات بالاتصال الفوري بالخط الساخن للأمانة العامة للصحة النفسية وعلاج الإدمان (16328 - مجاناً على مدار 24 ساعة)، أو الإسعاف (123) في حالات الطوارئ الطبية العاجلة.

# أدوات الدعم والتأقلم:
- عند ملاحظة نوبات هلع، تسارع في الأنفاس، أو قلق مفرط، استخدمي أداة `trigger_grounding_exercise` لمشاركة تمرين التنفس المربع 4-4-4 أو تقنية 5-4-3-2-1 للتهدئة الحاضرة.

```

---

## 7. backend/services/psychiatric_tools.py
**Path**: `backend/services/psychiatric_tools.py`  
**Role**: Psychiatric Function Calling Declarations & Execution Handlers  
**Forensic Impact**: Defines function declarations (trigger_grounding_exercise, escalate_crisis) sent in the Gemini setup payload. In Gemini Live, tool calls pause voice generation until tool responses are returned.  

```python
"""
Clinical Function Calling Declarations & Execution for Fadfada Psychiatric Agent.
Provides Gemini Live with tools for grounding exercises and crisis escalation.
"""

from typing import Any, Dict, List

GEMINI_PSYCHIATRIC_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "trigger_grounding_exercise",
        "description": "Triggers a visual and structured clinical grounding exercise (Square Breathing 4-4-4 or 5-4-3-2-1 Sensory Grounding) on the user's screen when they experience acute anxiety, panic, or racing thoughts.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "exercise_name": {
                    "type": "STRING",
                    "description": "The specific grounding exercise to trigger: 'square_breathing' (التنفس المربع 4-4-4) or 'sensory_54321' (تمرين الحواس الخمس 5-4-3-2-1).",
                    "enum": ["square_breathing", "sensory_54321"]
                },
                "guidance_ar": {
                    "type": "STRING",
                    "description": "Gentle, brief verbal instruction in Egyptian Colloquial Arabic explaining the current step to the user."
                }
            },
            "required": ["exercise_name", "guidance_ar"]
        }
    },
    {
        "name": "escalate_crisis",
        "description": "Immediately escalates an acute psychiatric emergency, triggering emergency UI banners and guiding the user to Egyptian emergency hotlines (16328 for Mental Health, 123 for Ambulance). MUST be called if the user mentions suicidal ideation, self-harm, or severe danger.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "urgency_level": {
                    "type": "STRING",
                    "description": "Level of urgency: 'immediate' (life threat / self-harm) or 'high' (severe acute distress).",
                    "enum": ["immediate", "high"]
                },
                "reason": {
                    "type": "STRING",
                    "description": "Brief clinical reason for escalation."
                }
            },
            "required": ["urgency_level", "reason"]
        }
    }
]


def execute_psychiatric_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Executes clinical tools called by Gemini Live and returns response payload."""
    if name == "trigger_grounding_exercise":
        exercise = args.get("exercise_name", "square_breathing")
        guidance = args.get("guidance_ar", "خد نفس هادي وعميق..")
        return {
            "status": "success",
            "exercise": exercise,
            "title_ar": "التنفس المربع (4-4-4)" if exercise == "square_breathing" else "تمرين الحواس الخمس (5-4-3-2-1)",
            "guidance_ar": guidance,
            "instruction": "Explain the step calmly in one gentle sentence in Egyptian Arabic and invite the user to breathe or observe."
        }

    elif name == "escalate_crisis":
        urgency = args.get("urgency_level", "immediate")
        reason = args.get("reason", "Crisis indicator detected")
        return {
            "status": "escalated",
            "urgency": urgency,
            "primary_hotline": {
                "name": "الخط الساخن للأمانة العامة للصحة النفسية وعلاج الإدمان (MOHP)",
                "number": "16328",
                "availability": "24/7 مجاناً"
            },
            "ambulance": "123",
            "instruction": "Urge the patient warmly to contact 16328 or 123 immediately and assure them that their life and safety are the top priority."
        }

    return {"status": "unrecognized_tool", "name": name}

```

---

## 8. frontend/index.html
**Path**: `frontend/index.html`  
**Role**: Client UI Layout, Audio Permission Shell, and Script Loading Order  
**Forensic Impact**: Defines the HTML structure, audio visualizer canvas, dialogue stream container, audio control buttons, and loads audio-streamer.js followed by app.js.  

```html
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>فضفضة (Fadfada) — رفيق الاستماع والدعم النفسي بالعامية المصرية</title>
  <!-- Cairo Font -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
  <!-- Persistent Emergency Top Banner -->
  <aside class="crisis-bar" role="alert" aria-label="أرقام الطوارئ المصرية">
    <div class="crisis-content">
      <span class="crisis-icon">🚨</span>
      <span class="crisis-text">
        <strong>حالات الطوارئ والأزمات النفسية العاجلة:</strong> الخط الساخن للأمانة العامة للصحة النفسية:
        <a href="tel:16328" class="hotline-link">16328</a> (24/7 مجاناً) | الإسعاف: <a href="tel:123" class="hotline-link">123</a>
      </span>
      <button class="crisis-more-btn" onclick="openCrisisModal()" aria-label="عرض كل خطوط الطوارئ">عرض كل الأرقام</button>
    </div>
  </aside>

  <!-- Application Shell -->
  <div class="app-container">
    <!-- Header -->
    <header class="app-header">
      <div class="brand">
        <h1 class="logo-title">فضفضة <span>(Fadfada)</span></h1>
        <p class="tagline">مساحة استماع آمنة وداعمة بالعامية المصرية</p>
      </div>

      <div class="header-actions">
        <button class="nav-pill-btn" onclick="openProtocolsDrawer()">
          🌿 تمارين التنفس والدعم
        </button>
        <button class="nav-pill-btn" onclick="openPrivacyModal()">
          🔒 الخصوصية والموافقة (Law 151)
        </button>
        <a href="/design-variants-static/index.html" target="_blank" class="nav-pill-btn variants-link">
          🎨 بدائل التصميم (4 Variants)
        </a>
      </div>
    </header>

    <!-- Main Sanctuary Stage -->
    <main class="sanctuary-stage">
      <!-- Voice Visualizer Stage -->
      <section class="visualizer-wrapper" aria-label="هالة الصوت التفاعلية">
        <div class="canvas-container">
          <canvas id="voiceOrbCanvas" width="280" height="280" aria-hidden="true"></canvas>
          <div class="orb-status-indicator" id="orbStatusText">مستعد للحديث</div>
        </div>
      </section>

      <!-- Structured Conversation Message Stream -->
      <section class="dialogue-container" aria-live="polite">
        <div class="conversation-feed" id="conversationFeed">
          <!-- Initial Welcome Message from Fadfada -->
          <div class="chat-message message-agent">
            <div class="message-meta">
              <span class="sender-tag">فضفضة 🌿</span>
              <span class="time-tag">الآن</span>
            </div>
            <div class="message-bubble">
              أهلاً بيك في مساحتك الآمنة مع فضفضة.. أنا هنا وسامعاك بكل اهتمام وهدوء. لما تحب تتكلم، اضغط على "ابدأ الفضفضة" وخد وقتك تماماً في الكلام.
            </div>
          </div>
        </div>

        <!-- Live Streaming Interim Indicator -->
        <div class="streaming-interim-card" id="streamingInterimCard" style="display: none;">
          <div class="streaming-meta">
            <span class="pulsing-voice-dot"></span>
            <span id="streamingSpeakerTag">فضفضة يتحدث الآن...</span>
          </div>
          <div class="streaming-text" id="streamingInterimText">...</div>
        </div>
      </section>

      <!-- Primary Audio & Interaction Controls -->
      <section class="controls-container" aria-label="أدوات التحكم الصوتي">
        <div class="primary-controls">
          <button id="btnStartVoice" class="control-btn btn-record" onclick="toggleVoiceSession()">
            <span class="btn-icon">🎙️</span>
            <span class="btn-label" id="btnRecordLabel">ابدأ الفضفضة</span>
          </button>
          <button id="btnFinishTurn" class="control-btn btn-turn" onclick="triggerTurnComplete()" disabled>
            <span>خلصت كلامي (رد عليا)</span>
          </button>
          <button id="btnInterrupt" class="control-btn btn-interrupt" onclick="triggerBargeIn()" disabled>
            <span>لحظة / مقاطعة</span>
          </button>
        </div>

        <!-- Typed Fallback Input Bar -->
        <div class="fallback-input-container">
          <input type="text" id="typedInput" class="typed-input" placeholder="أو اكتب فضفضتك هنا واضغط إرسال.." onkeydown="handleInputKey(event)">
          <button id="btnSendText" class="btn-send-text" onclick="sendTypedTurn()">إرسال</button>
        </div>
      </section>
    </main>

    <!-- Footer Disclaimers -->
    <footer class="app-footer">
      <p>
        فضفضة رفيق ذكاء اصطناعي للمساندة العاطفية وليس بديلاً عن الطبيب النفسي البشري أو التشخيص السريري.
        جميع البيانات محفوظة وفقاً للقانون المصري رقم 151 لسنة 2020 لحماية البيانات الشخصية.
      </p>
    </footer>
  </div>

  <!-- Coping Protocols Drawer -->
  <div class="drawer-overlay" id="protocolsDrawer" onclick="closeProtocolsDrawer(event)">
    <div class="drawer-panel" onclick="event.stopPropagation()">
      <div class="drawer-header">
        <h3>تمارين الدعم الإكلينيكي المعتمدة</h3>
        <button class="close-btn" onclick="closeProtocolsDrawer()">✕</button>
      </div>
      <div class="drawer-body" id="protocolsList">
        <!-- Rendered dynamically from /api/protocols -->
        <div class="loading-spinner">جارٍ تحميل التمارين..</div>
      </div>
    </div>
  </div>

  <!-- Law 151/2020 Privacy & Consent Modal -->
  <div class="modal-overlay" id="privacyModal" onclick="closePrivacyModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3>حوكمة الذاكرة والخصوصية (القانون المصري 151/2020)</h3>
        <button class="close-btn" onclick="closePrivacyModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="consent-box">
          <div class="consent-info">
            <strong>الموافقة على حفظ الذاكرة الطولية (Long-term Memory)</strong>
            <p>تسمح لفضفضة بتذكر تفضيلاتك وأهدافك الشخصية لدعمك في الجلسات القادمة دون حفظ أي تشخيصات طبية.</p>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="consentToggle" onchange="toggleConsent(this.checked)">
            <span class="slider"></span>
          </label>
        </div>

        <div class="active-memories-section">
          <h4>الذكريات المحفوظة حالياً لحسابك:</h4>
          <div id="patientMemoriesList" class="memories-list">
            <p class="empty-state">لا توجد ذكريات محفوظة حالياً.</p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Emergency Hotlines Directory Modal -->
  <div class="modal-overlay" id="crisisModal" onclick="closeCrisisModal(event)">
    <div class="modal-card emergency-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3>🚨 أرقام الطوارئ والدعم النفسي في مصر</h3>
        <button class="close-btn" onclick="closeCrisisModal()">✕</button>
      </div>
      <div class="modal-body" id="crisisList">
        <!-- Rendered dynamically from /api/crisis -->
      </div>
    </div>
  </div>

  <script src="/static/js/audio-streamer.js"></script>
  <script src="/static/js/app.js"></script>
</body>
</html>

```

---

## 9. run.py
**Path**: `run.py`  
**Role**: Production Launcher, Port Auto-Discovery, and UTF-8 Console Setup  
**Forensic Impact**: Initializes server environment, handles port binding, and starts Uvicorn with UTF-8 safe stdout/stderr.  

```python
"""
One-Click Production Launcher for Fadfada (فضفضة) AI Psychiatric Agent Demo.
Auto-detects free ports to avoid port collision with other local services.
Safe UTF-8 and cp1252 Windows console handling.
"""

import socket
import sys
import uvicorn

# Configure UTF-8 safe stdout for Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend import config


def find_free_port(preferred_port: int, max_tries: int = 30) -> int:
    """Finds an available TCP port starting from preferred_port."""
    for p in range(preferred_port, preferred_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((config.HOST, p))
                return p
            except OSError:
                continue
    return preferred_port


def main():
    port = find_free_port(config.PORT)

    banner = f"""
========================================================================
  FADFADA - AI Psychiatric Voice Companion Demo Launcher
  Egyptian Colloquial Arabic (Al-Aamiya)
========================================================================
  * Host: {config.HOST}
  * Active Port: {port}
  * Mode: {'Google Gemini Live Cloud' if config.GEMINI_API_KEY else 'Smart Local Simulation Engine'}
  * Model: {config.MODEL_LIVE}
  * Voice: {config.DEFAULT_VOICE}
------------------------------------------------------------------------
  -> Web Application:               http://localhost:{port}/
  -> 4 Design Variants Comparison:  http://localhost:{port}/design-variants-static/index.html
  -> Interactive OpenAPI Docs:       http://localhost:{port}/docs
  -> Health Check:                  http://localhost:{port}/health
========================================================================
"""
    try:
        print(banner)
    except UnicodeEncodeError:
        print(f"Fadfada server running at http://localhost:{port}/")

    uvicorn.run(
        "backend.app:app",
        host=config.HOST,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()

```

---
