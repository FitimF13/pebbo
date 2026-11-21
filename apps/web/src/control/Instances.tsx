import { useCallback, useEffect, useState, type FormEvent } from 'react';

/** Two Pebbos (for example home and office): pairing and end-of-day handoffs with approval. */

interface Peer {
  id: number;
  name: string;
  address: string;
  created_at: number;
}

interface Handoff {
  id: number;
  peer: string;
  direction: 'out' | 'in';
  person: string;
  content: string;
  status: 'pending' | 'sent' | 'rejected' | 'failed' | 'received';
  created_at: number;
}

interface Overview {
  name: string;
  address: string;
  peers: Peer[];
  handoffs: Handoff[];
}

const BASE = '/api/control/instances';

async function call<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    const detail = (await response.json().catch(() => undefined)) as { detail?: unknown } | undefined;
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Das hat nicht geklappt.');
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

const STATUS: Record<Handoff['status'], string> = {
  pending: 'Wartet auf Freigabe',
  sent: 'Gesendet',
  rejected: 'Abgelehnt',
  failed: 'Nicht zugestellt',
  received: 'Empfangen',
};

export function Instances() {
  const [data, setData] = useState<Overview>();
  const [error, setError] = useState<string>();
  const [code, setCode] = useState<string>();
  const [address, setAddress] = useState('');
  const [peerCode, setPeerCode] = useState('');

  const load = useCallback(async () => {
    try {
      setData(await call<Overview>(''));
    } catch {
      setError('Die Instanzen konnten nicht geladen werden.');
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(interval);
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Das hat nicht geklappt.');
    }
    await load();
  }

  function connect(event: FormEvent) {
    event.preventDefault();
    void run(() => call('/connect', 'POST', { address: address.trim(), code: peerCode }));
    setPeerCode('');
  }

  if (!data) return <p className="control-empty">Lädt …</p>;
  const pending = data.handoffs.filter((handoff) => handoff.status === 'pending' && handoff.direction === 'out');

  return (
    <div className="stack">
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      {pending.map((handoff) => (
        <div key={handoff.id} className="card claim">
          <p>
            <strong>{handoff.person}</strong> möchte eine Übergabe an <strong>{handoff.peer}</strong> senden:
          </p>
          <p className="handoff-content">{handoff.content}</p>
          <div className="row">
            <button type="button" className="primary" onClick={() => void run(() => call(`/handoffs/${handoff.id}`, 'POST', { approve: true }))}>
              Freigeben und senden
            </button>
            <button type="button" className="quiet" onClick={() => void run(() => call(`/handoffs/${handoff.id}`, 'POST', { approve: false }))}>
              Ablehnen
            </button>
          </div>
        </div>
      ))}

      <p className="hint">
        Diese Instanz heisst <strong>{data.name}</strong> und ist unter {data.address} erreichbar. Eine zweite Instanz
        (zum Beispiel im Büro) hat ihre eigenen Daten. Sie kann nur Übergaben schicken, die hier freigegeben wurden.
      </p>

      {data.peers.length === 0 ? (
        <p className="control-empty">Noch keine zweite Instanz verbunden.</p>
      ) : (
        <ul className="list" aria-label="Verbundene Instanzen">
          {data.peers.map((peer) => (
            <li key={peer.id} className="card item">
              <div className="item-main">
                <p className="item-title">{peer.name}</p>
                <p className="item-meta">{peer.address}</p>
              </div>
              <button type="button" className="danger" onClick={() => void run(() => call(`/${peer.id}`, 'DELETE'))}>
                Trennen
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="card form-row">
        <div className="field grow">
          <span>Diese Instanz mit einer anderen verbinden lassen</span>
          {code ? <p className="code-display">{code}</p> : <p className="item-meta">Erzeugt einen Code für die andere Instanz.</p>}
        </div>
        <button type="button" className="primary" onClick={() => void run(async () => setCode((await call<{ code: string }>('/invite', 'POST')).code))}>
          Code erzeugen
        </button>
      </div>

      <form className="card form-row" onSubmit={connect}>
        <label className="field grow">
          <span>Adresse der anderen Instanz</span>
          <input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="http://192.168.1.10:8100" />
        </label>
        <label className="field">
          <span>Ihr Code</span>
          <input
            value={peerCode}
            onChange={(event) => setPeerCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            inputMode="numeric"
            className="code-input"
            placeholder="123456"
          />
        </label>
        <button type="submit" className="primary" disabled={peerCode.length !== 6 || !address.trim()}>
          Verbinden
        </button>
      </form>

      {data.handoffs.length > 0 && (
        <section className="group" aria-label="Übergaben">
          <h3>Übergaben</h3>
          <ul className="list">
            {data.handoffs.map((handoff) => (
              <li key={handoff.id} className="card item">
                <div className="item-main">
                  <p>{handoff.content}</p>
                  <p className="item-meta">
                    {handoff.direction === 'out' ? `An ${handoff.peer}` : `Von ${handoff.peer}`} · {handoff.person} ·{' '}
                    {STATUS[handoff.status]}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
