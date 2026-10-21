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
          autoGainControl: true
        }
      });

      const track = this.mediaStream?.getAudioTracks?.()[0];
      console.info('[AudioStreamer] Effective mic settings:', track?.getSettings?.());

      const hardwareSampleRate = this.audioContext.sampleRate;
      console.log(`[AudioStreamer] Microphone opened via shared AudioContext at ${hardwareSampleRate} Hz`);

      this.inputSource = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.inputAnalyser = this.audioContext.createAnalyser();
      this.inputAnalyser.fftSize = 256;
      this.inputSource.connect(this.inputAnalyser);

      // Buffer size 2048 gives ~42.6ms chunks at 48kHz
      this.scriptProcessor = this.audioContext.createScriptProcessor(2048, 1, 1);

      this.scriptProcessor.onaudioprocess = (e) => {
        if (this.isMuted) return;

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

        // Note: Do not drop microphone frames while agent is playing.
        // Keeping the microphone stream flowing continuously to Gemini Live allows
        // Gemini Live's native server-side VAD to detect user speech naturally without
        // dropping the first 170ms of an interruption.
        // When Gemini Live detects speech, it emits serverContent.interrupted,
        // which immediately halts and flushes local playback via stopPlayback().

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

        // Stream 16kHz PCM audio chunk to callback
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
