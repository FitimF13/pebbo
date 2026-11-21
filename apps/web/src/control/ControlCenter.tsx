import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Compute } from './Compute';
import { Instances } from './Instances';
import {
  controlApi,
  ROLE_NAMES,
  type Device,
  type Memory,
  type Person,
  type Reminder,
  type Role,
  type VoiceClaim,
} from './api';
import { Calendar } from './Calendar';
import { Integrations } from './Integrations';
import { Phones } from './Phones';
import { Routines } from './Routines';

type Tab =
  | 'people'
  | 'memories'
  | 'reminders'
  | 'routines'
  | 'calendar'
  | 'devices'
  | 'integrations'
  | 'compute'
  | 'instances';

const TABS: { id: Tab; label: string }[] = [
  { id: 'people', label: 'Personen' },
  { id: 'memories', label: 'Gedächtnis' },
  { id: 'reminders', label: 'Erinnerungen' },
  { id: 'routines', label: 'Routinen' },
  { id: 'calendar', label: 'Kalender' },
  { id: 'devices', label: 'Geräte' },
  { id: 'integrations', label: 'Integrationen' },
  { id: 'compute', label: 'Rechner' },
  { id: 'instances', label: 'Büro & Zuhause' },
];

interface Data {
  people: Person[];
  claims: VoiceClaim[];
  memories: Memory[];
  reminders: Reminder[];
  devices: Device[];
}

const REFRESH_MS = 4000;

/** The web control centre: people and voices, memories and reminders. */
export function ControlCenter({ onClose }: { onClose(): void }) {
  const [tab, setTab] = useState<Tab>('people');
  const [data, setData] = useState<Data>();
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const [people, claims, memories, reminders, devices] = await Promise.all([
        controlApi.people(),
        controlApi.voiceClaims(),
        controlApi.memories(),
        controlApi.reminders(),
        controlApi.devices(),
      ]);
      setData({ people, claims, memories, reminders, devices });
      setError(undefined);
    } catch {
      setError('Das Kontrollzentrum erreicht den Pebbo-Kern gerade nicht.');
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      try {
        await action();
        setError(undefined);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Das hat nicht geklappt.');
      }
      await load();
    },
    [load],
  );

  return (
    <section className="control-centre" aria-labelledby="control-title">
      <header className="control-header">
        <h2 id="control-title">Kontrollzentrum</h2>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Kontrollzentrum schliessen">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </header>

      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}

      {!data ? (
        <p className="control-empty">Lädt …</p>
      ) : data.people.length === 0 ? (
        <OwnerSetup onCreate={(name) => run(() => controlApi.addPerson(name, 'owner'))} />
      ) : (
        <>
          <VoiceClaims claims={data.claims} people={data.people} run={run} />
          <nav className="tabs" aria-label="Bereiche">
            {TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                className="tab"
                aria-pressed={tab === id}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          {tab === 'people' && <People people={data.people} run={run} />}
          {tab === 'memories' && <Memories memories={data.memories} people={data.people} run={run} />}
          {tab === 'reminders' && <Reminders reminders={data.reminders} people={data.people} run={run} />}
          {tab === 'routines' && <Routines people={data.people} />}
          {tab === 'calendar' && <Calendar people={data.people} />}
          {tab === 'devices' && (
            <>
              <Devices devices={data.devices} run={run} />
              <Phones people={data.people} />
            </>
          )}
          {tab === 'integrations' && <Integrations />}
          {tab === 'compute' && <Compute />}
          {tab === 'instances' && <Instances />}
        </>
      )}
    </section>
  );
}

type Run = (action: () => Promise<unknown>) => Promise<void>;

function OwnerSetup({ onCreate }: { onCreate(name: string): Promise<void> }) {
  const [name, setName] = useState('');
  return (
    <form
      className="card setup"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) void onCreate(name.trim());
      }}
    >
      <h3>Willkommen bei Pebbo</h3>
      <p>Wie heisst du? Du wirst der Besitzer dieses Pebbos und kannst später weitere Personen einladen.</p>
      <label className="field">
        <span>Dein Vorname</span>
        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={60} autoFocus />
      </label>
      <button type="submit" className="primary" disabled={!name.trim()}>
        Los geht's
      </button>
    </form>
  );
}

function VoiceClaims({ claims, people, run }: { claims: VoiceClaim[]; people: Person[]; run: Run }) {
  if (claims.length === 0) return null;
  return (
    <div className="claims">
      {claims.map((claim) => {
        const match = people.find((person) => person.id === claim.person_id);
        return (
          <div key={claim.id} className="card claim">
            <p>
              Eine neue Stimme hat sich als <strong>{claim.claimed_name}</strong> vorgestellt.
              {!match && ' Diese Person ist noch nicht eingeladen.'}
            </p>
            <div className="row">
              {match ? (
                <button type="button" className="primary" onClick={() => void run(() => controlApi.confirmClaim(claim.id, match.id))}>
                  Ja, das ist {match.name}
                </button>
              ) : (
                <ClaimAssign claim={claim} people={people} run={run} />
              )}
              <button type="button" className="quiet" onClick={() => void run(() => controlApi.rejectClaim(claim.id))}>
                Ablehnen
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ClaimAssign({ claim, people, run }: { claim: VoiceClaim; people: Person[]; run: Run }) {
  const [personId, setPersonId] = useState(people[0]?.id ?? 0);
  return (
    <>
      <select aria-label="Person auswählen" value={personId} onChange={(event) => setPersonId(Number(event.target.value))}>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.name}
          </option>
        ))}
      </select>
      <button type="button" className="primary" onClick={() => void run(() => controlApi.confirmClaim(claim.id, personId))}>
        Zuordnen
      </button>
    </>
  );
}

function voiceStatus(person: Person): string {
  if (!person.voice_enabled) return 'Stimmerkennung aus';
  if (person.voice_samples === 0) return 'Stimme noch unbekannt';
  return `Stimme bekannt · ${person.voice_samples} ${person.voice_samples === 1 ? 'Probe' : 'Proben'}`;
}

function People({ people, run }: { people: Person[]; run: Run }) {
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('adult');

  function add(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    void run(() => controlApi.addPerson(name.trim(), role));
    setName('');
  }

  return (
    <div className="stack">
      <ul className="list" aria-label="Personen">
        {people.map((person) => (
          <li key={person.id} className="card item">
            <div className="item-main">
              <p className="item-title">
                {person.name} <span className="badge">{ROLE_NAMES[person.role]}</span>
              </p>
              <p className="item-meta">{voiceStatus(person)}</p>
            </div>
            <div className="row">
              <button
                type="button"
                className="quiet"
                onClick={() => void run(() => controlApi.updatePerson(person.id, { voice_enabled: !person.voice_enabled }))}
              >
                {person.voice_enabled ? 'Stimme aus' : 'Stimme an'}
              </button>
              {person.voice_samples > 0 && (
                <button type="button" className="quiet" onClick={() => void run(() => controlApi.resetVoice(person.id))}>
                  Stimme vergessen
                </button>
              )}
              {person.role !== 'owner' && (
                <button type="button" className="danger" onClick={() => void run(() => controlApi.removePerson(person.id))}>
                  Entfernen
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <form className="card form-row" onSubmit={add}>
        <label className="field grow">
          <span>Neue Person</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={60} placeholder="Vorname" />
        </label>
        <label className="field">
          <span>Rolle</span>
          <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
            <option value="adult">Erwachsen</option>
            <option value="child">Kind</option>
            <option value="colleague">Kollege</option>
          </select>
        </label>
        <button type="submit" className="primary" disabled={!name.trim()}>
          Einladen
        </button>
      </form>
      <p className="hint">
        Pebbo lernt Stimmen nebenbei. Wenn er eine unbekannte Stimme hört und sich die Person vorstellt, erscheint
        oben eine Anfrage zum Bestätigen. Er speichert nur einen Stimm-Fingerabdruck, nie Aufnahmen.
      </p>
    </div>
  );
}

function Memories({ memories, people, run }: { memories: Memory[]; people: Person[]; run: Run }) {
  const [owner, setOwner] = useState<string>(String(people[0]?.id ?? 'household'));
  const [text, setText] = useState('');
  const groups: { key: string; title: string; items: Memory[] }[] = [
    ...people.map((person) => ({
      key: String(person.id),
      title: person.name,
      items: memories.filter((memory) => memory.person_id === person.id),
    })),
    { key: 'household', title: 'Haushalt', items: memories.filter((memory) => memory.person_id === null) },
  ];

  function add(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    void run(() => controlApi.addMemory(owner === 'household' ? null : Number(owner), text.trim()));
    setText('');
  }

  return (
    <div className="stack">
      {groups.map((group) => (
        <section key={group.key} className="group" aria-label={`Gedächtnis: ${group.title}`}>
          <h3>{group.title}</h3>
          {group.items.length === 0 ? (
            <p className="control-empty">Noch nichts gespeichert.</p>
          ) : (
            <ul className="list">
              {group.items.map((memory) => (
                <li key={memory.id} className="card item">
                  <div className="item-main">
                    <p>{memory.text}</p>
                    {memory.kind === 'summary' && <p className="item-meta">Gesprächszusammenfassung</p>}
                    {memory.source === 'learned' && <p className="item-meta">Nebenbei gelernt</p>}
                  </div>
                  <button type="button" className="quiet" onClick={() => void run(() => controlApi.deleteMemory(memory.id))}>
                    Löschen
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <form className="card form-row" onSubmit={add}>
        <label className="field">
          <span>Für</span>
          <select value={owner} onChange={(event) => setOwner(event.target.value)}>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.name}
              </option>
            ))}
            <option value="household">Haushalt</option>
          </select>
        </label>
        <label className="field grow">
          <span>Neuer Eintrag</span>
          <input value={text} onChange={(event) => setText(event.target.value)} maxLength={500} placeholder="z. B. Mag Kaffee ohne Zucker" />
        </label>
        <button type="submit" className="primary" disabled={!text.trim()}>
          Merken
        </button>
      </form>
    </div>
  );
}

function Reminders({ reminders, people, run }: { reminders: Reminder[]; people: Person[]; run: Run }) {
  if (reminders.length === 0) {
    return <p className="control-empty">Keine offenen Erinnerungen. Sag zum Beispiel «Erinnere mich in zehn Minuten an den Tee».</p>;
  }
  return (
    <ul className="list" aria-label="Erinnerungen">
      {reminders.map((reminder) => (
        <li key={reminder.id} className="card item">
          <div className="item-main">
            <p className="item-title">{reminder.text}</p>
            <p className="item-meta">
              {people.find((person) => person.id === reminder.person_id)?.name ?? 'Unbekannt'} · {reminder.due_text}
            </p>
          </div>
          <button type="button" className="quiet" onClick={() => void run(() => controlApi.cancelReminder(reminder.id))}>
            Löschen
          </button>
        </li>
      ))}
    </ul>
  );
}

function lastSeen(device: Device): string {
  if (device.online) return 'Verbunden';
  if (device.status === 'pending') return 'Wartet auf Kopplung';
  if (!device.last_seen_at) return 'Noch nie verbunden';
  const minutes = Math.round((Date.now() / 1000 - device.last_seen_at) / 60);
  if (minutes < 2) return 'Gerade eben gesehen';
  if (minutes < 120) return `Vor ${minutes} Minuten gesehen`;
  return `Zuletzt gesehen am ${new Date(device.last_seen_at * 1000).toLocaleDateString('de-CH')}`;
}

function Devices({ devices, run }: { devices: Device[]; run: Run }) {
  const [code, setCode] = useState('');
  const paired = devices.filter((device) => device.status === 'paired');
  const waiting = devices.some((device) => device.status === 'pending');

  function pair(event: FormEvent) {
    event.preventDefault();
    if (code.length !== 6) return;
    void run(() => controlApi.pairDevice(code));
    setCode('');
  }

  return (
    <div className="stack">
      {paired.length === 0 ? (
        <p className="control-empty">Noch kein Pebbo-Körper gekoppelt.</p>
      ) : (
        <ul className="list" aria-label="Geräte">
          {paired.map((device) => (
            <DeviceItem key={device.id} device={device} run={run} />
          ))}
        </ul>
      )}
      <form className="card form-row" onSubmit={pair}>
        <label className="field grow">
          <span>Kopplungscode vom Bildschirm des Geräts</span>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            className="code-input"
          />
        </label>
        <button type="submit" className="primary" disabled={code.length !== 6}>
          Koppeln
        </button>
      </form>
      <p className="hint">
        {waiting ? 'Ein Gerät wartet gerade auf die Kopplung. ' : ''}
        Ein neuer Pebbo-Körper zeigt beim Start einen sechsstelligen Code und sagt ihn an. Gib ihn hier ein, dann
        verbindet er sich nur noch mit diesem Pebbo. Wie du ein Gerät einrichtest, steht in der Anleitung unter
        hardware/README.md.
      </p>
    </div>
  );
}

function DeviceItem({ device, run }: { device: Device; run: Run }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.name);
  return (
    <li className="card item">
      <div className="item-main">
        {editing ? (
          <form
            className="row"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) void run(() => controlApi.renameDevice(device.id, name.trim()));
              setEditing(false);
            }}
          >
            <input aria-label="Gerätename" value={name} onChange={(event) => setName(event.target.value)} maxLength={40} autoFocus />
            <button type="submit" className="primary">
              Speichern
            </button>
          </form>
        ) : (
          <p className="item-title">
            {device.name} <span className={device.online ? 'badge online' : 'badge'}>{device.online ? 'Online' : 'Offline'}</span>
          </p>
        )}
        <p className="item-meta">
          {lastSeen(device)} · {device.board}
        </p>
      </div>
      <div className="row">
        {!editing && (
          <button type="button" className="quiet" onClick={() => setEditing(true)}>
            Umbenennen
          </button>
        )}
        <button type="button" className="danger" onClick={() => void run(() => controlApi.removeDevice(device.id))}>
          Entfernen
        </button>
      </div>
    </li>
  );
}
