import { useCallback, useEffect, useRef, useState } from 'react';
import type { PebboState } from '../face/expressions';
import { PebboConnection } from './connection';
import type { PebboEvent } from './rtvi';

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'error';

const EMOTION_LINGER_MS = 3000;

/** Captions show what Pebbo says without markdown emphasis or emojis. */
export function cleanCaption(text: string): string {
  return text
    .replace(/\[\s*[a-zA-Z]{2,15}\s*\]/g, '')
    .replace(/\*+([^*]+)\*+/g, '$1')
    .replace(/\p{Extended_Pictographic}/gu, '')
    .replace(/\s{2,}/g, ' ');
}

export interface Pebbo {
  status: ConnectionStatus;
  error?: string | undefined;
  state: PebboState;
  muted: boolean;
  level: number;
  heard: string;
  says: string;
  start(): Promise<void>;
  stop(): void;
  toggleMute(): void;
}

const initialState: PebboState = {
  connected: false,
  awake: false,
  userSpeaking: false,
  thinking: false,
  botSpeaking: false,
  emotionLingers: false,
};

/** Connects to the Pebbo core and keeps the conversation state for the face. */
export function usePebbo(): Pebbo {
  const [status, setStatus] = useState<ConnectionStatus>('idle');
  const [error, setError] = useState<string>();
  const [state, setState] = useState<PebboState>(initialState);
  const [muted, setMuted] = useState(false);
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState('');
  const [says, setSays] = useState('');
  const connection = useRef<PebboConnection | undefined>(undefined);
  const audio = useRef<HTMLAudioElement | undefined>(undefined);
  const meter = useRef<{ context: AudioContext; frame: number } | undefined>(undefined);
  const linger = useRef(0);

  const handleEvent = useCallback((event: PebboEvent) => {
    switch (event.kind) {
      case 'user-speaking':
        setState((current) => ({ ...current, userSpeaking: event.speaking }));
        break;
      case 'thinking':
        setSays('');
        setState((current) => ({ ...current, thinking: true, emotion: undefined, emotionLingers: false }));
        break;
      case 'bot-speaking':
        window.clearTimeout(linger.current);
        setState((current) => ({ ...current, botSpeaking: event.speaking, thinking: false, emotionLingers: !event.speaking }));
        if (!event.speaking) {
          linger.current = window.setTimeout(
            () => setState((current) => ({ ...current, emotionLingers: false })),
            EMOTION_LINGER_MS,
          );
        }
        break;
      case 'emotion':
        setState((current) => ({ ...current, emotion: event.emotion }));
        break;
      case 'wake':
        setState((current) => ({ ...current, awake: event.awake }));
        break;
      case 'heard':
        setHeard(event.text);
        break;
      case 'says':
        setSays((current) => `${current} ${cleanCaption(event.text)}`.trim());
        break;
      case 'ready':
        break;
    }
  }, []);

  const stopMeter = useCallback(() => {
    if (!meter.current) return;
    cancelAnimationFrame(meter.current.frame);
    void meter.current.context.close();
    meter.current = undefined;
    setLevel(0);
  }, []);

  const startMeter = useCallback(
    (stream: MediaStream) => {
      stopMeter();
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      let lastLevel = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
        const next = Math.min(1, Math.sqrt(sum / samples.length) * 5);
        // Re-render only on visible changes, not on every animation frame.
        if (Math.abs(next - lastLevel) > 0.05 || (next === 0 && lastLevel !== 0)) {
          lastLevel = next;
          setLevel(next);
        }
        if (meter.current) meter.current.frame = requestAnimationFrame(tick);
      };
      meter.current = { context, frame: requestAnimationFrame(tick) };
    },
    [stopMeter],
  );

  const stop = useCallback(() => {
    connection.current?.disconnect();
    connection.current = undefined;
    stopMeter();
    if (audio.current) audio.current.srcObject = null;
    setState(initialState);
    setStatus('idle');
    setMuted(false);
  }, [stopMeter]);

  const start = useCallback(async () => {
    setStatus('connecting');
    setError(undefined);
    const player = audio.current ?? new Audio();
    player.autoplay = true;
    audio.current = player;
    const next = new PebboConnection({
      onEvent: handleEvent,
      onAudio: (stream) => {
        player.srcObject = stream;
        void player.play();
        startMeter(stream);
      },
      onClosed: () => {
        if (connection.current === next) stop();
      },
    });
    connection.current = next;
    try {
      await next.connect();
      setState((current) => ({ ...current, connected: true }));
      setStatus('connected');
    } catch (cause) {
      next.disconnect();
      connection.current = undefined;
      setStatus('error');
      setError(
        cause instanceof DOMException && cause.name === 'NotAllowedError'
          ? 'Pebbo darf das Mikrofon nicht benutzen. Erlaube den Zugriff in den Browser-Einstellungen.'
          : 'Pebbo ist gerade nicht erreichbar. Läuft der Pebbo-Kern?',
      );
    }
  }, [handleEvent, startMeter, stop]);

  const toggleMute = useCallback(() => {
    setMuted((current) => {
      connection.current?.setMuted(!current);
      return !current;
    });
  }, []);

  useEffect(() => () => connection.current?.disconnect(), []);

  return { status, error, state, muted, level, heard, says, start, stop, toggleMute };
}
