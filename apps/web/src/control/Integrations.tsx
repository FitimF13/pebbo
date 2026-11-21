import { useCallback, useEffect, useState, type FormEvent } from 'react';

/** Who may use an integration's tools. Guests never see device states, whatever is chosen here. */
export type IntegrationPermission = 'everyone' | 'household' | 'owner';

export interface IntegrationStatus {
  state: 'connected' | 'error' | 'disabled';
  message: string;
  tools: string[];
  live_context: boolean;
  checked_at: number | null;
}

/** An MCP server, for example Home Assistant. The core never sends the access token back. */
export interface Integration {
  id: number;
  name: string;
  url: string;
  permission: IntegrationPermission;
  enabled: boolean;
  allow_public: boolean;
  has_token: boolean;
  public_host: string | null;
  status: IntegrationStatus;
}

export interface IntegrationInput {
  name: string;
  url: string;
  token: string;
  permission: IntegrationPermission;
  allow_public: boolean;
}

export type IntegrationPatch = Partial<Omit<IntegrationInput, 'token'>> & { token?: string; enabled?: boolean };

export const PERMISSION_NAMES: Record<IntegrationPermission, string> = {
  everyone: 'Alle, auch Gäste',
  household: 'Haushalt',
  owner: 'Nur Besitzer',
};

const BASE = '/api/control/integrations';

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { 'Content-Type': 'application/json' };
  }
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    const detail = (await response.json().catch(() => undefined)) as { detail?: unknown } | undefined;
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Das hat nicht geklappt.');
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const integrationsApi = {
  list: () => request<Integration[]>(''),
  add: (input: IntegrationInput) => request<Integration>('', 'POST', input),
  update: (id: number, patch: IntegrationPatch) => request<Integration>(`/${id}`, 'PATCH', patch),
  refresh: (id: number) => request<Integration>(`/${id}/refresh`, 'POST'),
  remove: (id: number) => request<void>(`/${id}`, 'DELETE'),
};

function statusText(integration: Integration): string {
  const { status } = integration;
  if (status.state === 'disabled') return 'Ausgeschaltet';
  if (status.state === 'error') return status.message || 'Nicht verbunden';
  const tools = `${status.tools.length} ${status.tools.length === 1 ? 'Werkzeug' : 'Werkzeuge'}`;
  return status.live_context ? `${tools} · kennt den Zustand der Geräte` : tools;
}

const BADGES: Record<IntegrationStatus['state'], { label: string; className: string }> = {
  connected: { label: 'Verbunden', className: 'badge online' },
  error: { label: 'Fehler', className: 'badge' },
  disabled: { label: 'Aus', className: 'badge' },
};

/** Integrations tab of the control centre: MCP servers such as Home Assistant. */
export function Integrations() {
  const [integrations, setIntegrations] = useState<Integration[]>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setIntegrations(await integrationsApi.list());
    } catch {
      setError('Die Integrationen lassen sich gerade nicht laden.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      try {
        await action();
        setError(undefined);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Das hat nicht geklappt.');
      } finally {
        setBusy(false);
      }
      await load();
    },
    [load],
  );

  return (
    <div className="stack" aria-busy={busy}>
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      {!integrations ? (
        <p className="control-empty">Lädt …</p>
      ) : integrations.length === 0 ? (
        <p className="control-empty">Noch keine Integration. Füge zum Beispiel Home Assistant hinzu.</p>
      ) : (
        <ul className="list" aria-label="Integrationen">
          {integrations.map((integration) => (
            <IntegrationItem key={integration.id} integration={integration} run={run} />
          ))}
        </ul>
      )}
      <AddIntegration run={run} busy={busy} />
      <p className="hint">
        Pebbo benutzt die Werkzeuge eines MCP-Servers wie seine eigenen und entscheidet selbst, wann sie passen.
        Für Home Assistant aktivierst du dort die Integration «Model Context Protocol Server», gibst die
        gewünschten Geräte für Assist frei und erstellst einen langlebigen Zugangstoken. Die Adresse ist dann
        zum Beispiel http://homeassistant.local:8123/api/mcp/assist. Musik aus Music Assistant läuft über die
        Mediaplayer von Home Assistant. Die ganze Anleitung steht in docs/smart-home.md.
      </p>
    </div>
  );
}

type Run = (action: () => Promise<unknown>) => Promise<void>;

function IntegrationItem({ integration, run }: { integration: Integration; run: Run }) {
  const [token, setToken] = useState('');
  const [editingToken, setEditingToken] = useState(false);
  const badge = BADGES[integration.status.state];

  function saveToken(event: FormEvent) {
    event.preventDefault();
    if (!token.trim()) return;
    void run(() => integrationsApi.update(integration.id, { token: token.trim() }));
    setToken('');
    setEditingToken(false);
  }

  return (
    <li className="card item">
      <div className="item-main">
        <p className="item-title">
          {integration.name} <span className={badge.className}>{badge.label}</span>
        </p>
        <p className="item-meta">{statusText(integration)}</p>
        <p className="item-meta">
          {integration.url} · {integration.has_token ? 'Token gespeichert' : 'Kein Token'}
        </p>
        {integration.public_host && (
          <p className="item-meta">Öffentliche Adresse erlaubt: {integration.public_host}</p>
        )}
        {editingToken && (
          <form className="row" onSubmit={saveToken}>
            <input
              type="password"
              aria-label={`Neuer Token für ${integration.name}`}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoComplete="off"
              autoFocus
            />
            <button type="submit" className="primary" disabled={!token.trim()}>
              Speichern
            </button>
          </form>
        )}
      </div>
      <div className="row">
        <select
          aria-label={`Wer darf ${integration.name} benutzen`}
          value={integration.permission}
          onChange={(event) =>
            void run(() =>
              integrationsApi.update(integration.id, { permission: event.target.value as IntegrationPermission }),
            )
          }
        >
          {Object.entries(PERMISSION_NAMES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button type="button" className="quiet" onClick={() => void run(() => integrationsApi.refresh(integration.id))}>
          Neu verbinden
        </button>
        <button
          type="button"
          className="quiet"
          onClick={() => void run(() => integrationsApi.update(integration.id, { enabled: !integration.enabled }))}
        >
          {integration.enabled ? 'Ausschalten' : 'Einschalten'}
        </button>
        {!editingToken && (
          <button type="button" className="quiet" onClick={() => setEditingToken(true)}>
            Token ändern
          </button>
        )}
        <button type="button" className="danger" onClick={() => void run(() => integrationsApi.remove(integration.id))}>
          Entfernen
        </button>
      </div>
    </li>
  );
}

function AddIntegration({ run, busy }: { run: Run; busy: boolean }) {
  const [name, setName] = useState('Home Assistant');
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [permission, setPermission] = useState<IntegrationPermission>('household');
  const [allowPublic, setAllowPublic] = useState(false);
  const valid = name.trim() !== '' && /^https?:\/\/\S+$/.test(url.trim());

  function add(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const input = { name: name.trim(), url: url.trim(), token: token.trim(), permission, allow_public: allowPublic };
    void run(() => integrationsApi.add(input));
    setToken('');
    setUrl('');
  }

  return (
    <form className="card stack" onSubmit={add} aria-label="Integration hinzufügen">
      <div className="form-row">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={40} />
        </label>
        <label className="field grow">
          <span>Adresse des MCP-Servers</span>
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            maxLength={300}
            placeholder="http://homeassistant.local:8123/api/mcp/assist"
          />
        </label>
      </div>
      <div className="form-row">
        <label className="field grow">
          <span>Zugangstoken</span>
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
            placeholder="Langlebiger Zugangstoken"
          />
        </label>
        <label className="field">
          <span>Wer darf es benutzen</span>
          <select value={permission} onChange={(event) => setPermission(event.target.value as IntegrationPermission)}>
            {Object.entries(PERMISSION_NAMES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={allowPublic} onChange={(event) => setAllowPublic(event.target.checked)} />
        <span>
          Öffentliche Adresse erlauben. Nur nötig, wenn der Server nicht im Heimnetz läuft. Pebbo lässt dann genau
          diese Adresse durch seine Netzwerksperre.
        </span>
      </label>
      <div className="row">
        <button type="submit" className="primary" disabled={!valid || busy}>
          Hinzufügen
        </button>
      </div>
    </form>
  );
}
