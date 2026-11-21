import { useCallback, useEffect, useState, type FormEvent } from 'react';

/** Compute devices: the computers Pebbo thinks on, in the order Pebbo tries them. */

interface ComputeDevice {
  id: number;
  name: string;
  base_url: string;
  model: string;
  position: number;
  reachable: boolean | null;
  active: boolean;
  removable: boolean;
}

const BASE = '/api/control/compute';

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

function status(device: ComputeDevice): string {
  if (device.active) return 'Pebbo denkt gerade hier';
  if (device.reachable === null) return 'Wird geprüft';
  return device.reachable ? 'Erreichbar, als Reserve' : 'Nicht erreichbar';
}

export function Compute() {
  const [devices, setDevices] = useState<ComputeDevice[]>();
  const [error, setError] = useState<string>();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [model, setModel] = useState('pebbo-ministral');

  const load = useCallback(async () => {
    try {
      setDevices(await call<ComputeDevice[]>(''));
    } catch {
      setError('Die Rechner konnten nicht geladen werden.');
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 5000);
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

  function add(event: FormEvent) {
    event.preventDefault();
    const base = address.trim().replace(/\/$/, '');
    const url = /\/v1$/.test(base) ? base : `${base.includes(':') && base.split(':').length > 2 ? base : `${base}:11434`}/v1`;
    void run(() => call('', 'POST', { name: name.trim(), base_url: url, model: model.trim() }));
    setName('');
    setAddress('');
  }

  if (!devices) return <p className="control-empty">Lädt …</p>;
  return (
    <div className="stack">
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      <ul className="list" aria-label="Rechner">
        {devices.map((device, index) => (
          <li key={device.id} className="card item">
            <div className="item-main">
              <p className="item-title">
                {device.name}{' '}
                <span className={device.active ? 'badge online' : 'badge'}>{device.active ? 'Aktiv' : `#${index + 1}`}</span>
              </p>
              <p className="item-meta">
                {status(device)} · {device.model} · {device.base_url}
              </p>
            </div>
            <div className="row">
              {index > 0 && (
                <button type="button" className="quiet" onClick={() => void run(() => call(`/${device.id}`, 'PATCH', { position: -1 }))}>
                  Nach oben
                </button>
              )}
              {device.removable && (
                <button type="button" className="danger" onClick={() => void run(() => call(`/${device.id}`, 'DELETE'))}>
                  Entfernen
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <form className="card form-row" onSubmit={add}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Gaming-PC" maxLength={40} />
        </label>
        <label className="field grow">
          <span>Adresse mit Ollama</span>
          <input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="http://192.168.1.30" />
        </label>
        <label className="field">
          <span>Modell</span>
          <input value={model} onChange={(event) => setModel(event.target.value)} />
        </label>
        <button type="submit" className="primary" disabled={!name.trim() || !address.trim() || !model.trim()}>
          Hinzufügen
        </button>
      </form>
      <p className="hint">
        Pebbo nimmt den ersten erreichbaren Rechner in dieser Reihenfolge und prüft alle 20 Sekunden neu. Ist der
        Gaming-PC aus, denkt Pebbo auf dem nächsten weiter, mit einem kleineren Modell etwas einfacher. Rechner müssen im
        Heimnetz oder im privaten VPN sein.
      </p>
    </div>
  );
}
