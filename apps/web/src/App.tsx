import { useEffect, useState } from 'react';
import { ControlCenter } from './control/ControlCenter';
import { expressionFor } from './face/expressions';
import { Robot, type RingMode } from './Robot';
import { usePebbo, type Pebbo } from './voice/usePebbo';

function ringMode(pebbo: Pebbo): RingMode {
  const { state } = pebbo;
  if (pebbo.status !== 'connected') return 'asleep';
  if (pebbo.muted) return 'muted';
  if (state.botSpeaking) return 'speaking';
  if (state.userSpeaking) return 'listening';
  if (state.thinking) return 'thinking';
  return state.awake ? 'idle' : 'asleep';
}

function statusText(pebbo: Pebbo): string {
  if (pebbo.status === 'connecting') return 'Pebbo wacht auf …';
  if (pebbo.status !== 'connected') return 'Pebbo schläft';
  if (pebbo.muted) return 'Mikrofon aus';
  const { state } = pebbo;
  if (state.botSpeaking) return 'Pebbo spricht';
  if (state.userSpeaking) return 'Pebbo hört zu';
  if (state.thinking) return 'Pebbo denkt nach';
  return state.awake ? 'Ich höre dich' : 'Sag «Hey Pebbo»';
}

const CONTROL_HASH = '#/kontrollzentrum';

function useControlCenterRoute(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => window.location.hash === CONTROL_HASH);
  useEffect(() => {
    const update = () => setOpen(window.location.hash === CONTROL_HASH);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return [
    open,
    (next) => {
      window.location.hash = next ? CONTROL_HASH : '';
      setOpen(next);
    },
  ];
}

export function App() {
  const pebbo = usePebbo();
  const [controlOpen, setControlOpen] = useControlCenterRoute();
  const connected = pebbo.status === 'connected';
  const expression = expressionFor(pebbo.state);

  return (
    <>
      {controlOpen && <ControlCenter onClose={() => setControlOpen(false)} />}
      <main className="stage" hidden={controlOpen}>
      <button
        type="button"
        className="icon-button settings"
        onClick={() => setControlOpen(true)}
        aria-label="Kontrollzentrum öffnen"
      >
        <SettingsIcon />
      </button>
      <h1 className="visually-hidden">Pebbo</h1>
      <Robot expression={expression} ring={ringMode(pebbo)} level={pebbo.level} speaking={pebbo.state.botSpeaking} />

      <p className="status" role="status">
        <span className="status-dot" data-ring={ringMode(pebbo)} />
        {statusText(pebbo)}
      </p>

      {connected && (pebbo.heard || pebbo.says) && (
        <section className="captions" aria-label="Untertitel">
          {pebbo.heard && <p className="caption caption-user">{pebbo.heard}</p>}
          {pebbo.says && <p className="caption caption-pebbo">{pebbo.says}</p>}
        </section>
      )}

      {pebbo.error && (
        <p className="error" role="alert">
          {pebbo.error}
        </p>
      )}

      <nav className="controls" aria-label="Steuerung">
        {connected ? (
          <>
            <button
              type="button"
              className="control"
              aria-pressed={pebbo.muted}
              onClick={pebbo.toggleMute}
              title={pebbo.muted ? 'Mikrofon einschalten' : 'Mikrofon ausschalten'}
            >
              <MicIcon off={pebbo.muted} />
              <span className="visually-hidden">{pebbo.muted ? 'Mikrofon einschalten' : 'Mikrofon ausschalten'}</span>
            </button>
            <button type="button" className="control control-quiet" onClick={pebbo.stop} title="Pebbo schlafen legen">
              <PowerIcon />
              <span className="visually-hidden">Pebbo schlafen legen</span>
            </button>
          </>
        ) : (
          <button type="button" className="start" disabled={pebbo.status === 'connecting'} onClick={() => void pebbo.start()}>
            Pebbo aufwecken
          </button>
        )}
      </nav>
      </main>
    </>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </svg>
  );
}

function MicIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      {off && <path d="M4 4l16 16" />}
    </svg>
  );
}

function PowerIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v9" />
      <path d="M6.3 6.3a8 8 0 1 0 11.4 0" />
    </svg>
  );
}
