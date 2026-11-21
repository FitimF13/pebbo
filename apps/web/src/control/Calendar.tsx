import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { Person } from './api';
import { calendarApi, type CalendarOccurrence, type CalendarSource } from './calendarApi';

const REFRESH_MS = 4000;

function dayTitle(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString('de-CH', { weekday: 'long', day: 'numeric', month: 'long' });
}

function clockTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' });
}

function ownerName(people: Person[], personId: number | null): string {
  if (personId === null) return 'Haushalt';
  return people.find((person) => person.id === personId)?.name ?? 'Unbekannt';
}

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

/** Pebbo's local calendar for the next two weeks and read-only ICS subscriptions. */
export function Calendar({ people }: { people: Person[] }) {
  const [events, setEvents] = useState<CalendarOccurrence[]>();
  const [sources, setSources] = useState<CalendarSource[]>([]);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<{ id: number; text: string }>();

  const load = useCallback(async () => {
    try {
      const [list, feeds] = await Promise.all([calendarApi.events(), calendarApi.sources()]);
      setEvents(list);
      setSources(feeds);
    } catch {
      setError('Der Kalender kann gerade nicht geladen werden.');
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Das hat nicht geklappt.');
    }
    await load();
  }

  if (!events) return <p className="control-empty">Lädt …</p>;

  const days: { title: string; items: CalendarOccurrence[] }[] = [];
  for (const event of events) {
    const title = dayTitle(event.start);
    const last = days[days.length - 1];
    if (last?.title === title) last.items.push(event);
    else days.push({ title, items: [event] });
  }

  return (
    <div className="stack">
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      {days.length === 0 ? (
        <p className="control-empty">Keine Termine in den nächsten zwei Wochen.</p>
      ) : (
        days.map((day) => (
          <section key={day.title} className="group" aria-label={`Termine: ${day.title}`}>
            <h3>{day.title}</h3>
            <ul className="list">
              {day.items.map((event) => (
                <li key={`${event.event_id}-${event.start}`} className="card item">
                  <div className="item-main">
                    <p className="item-title">{event.title}</p>
                    <p className="item-meta">
                      {event.all_day ? 'Ganztägig' : clockTime(event.start)} · {ownerName(people, event.person_id)}
                      {event.recurring && ' · wiederholt sich'}
                      {event.source_id !== null && ' · abonniert'}
                    </p>
                  </div>
                  {event.source_id === null && (
                    <button type="button" className="quiet" onClick={() => void act(() => calendarApi.deleteEvent(event.event_id))}>
                      Löschen
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      <EventForm people={people} onAdd={(personId, title, start) => act(() => calendarApi.addEvent(personId, title, start))} />
      <section className="group" aria-label="Abonnierte Kalender">
        <h3>Abonnierte Kalender</h3>
        {sources.length === 0 ? (
          <p className="control-empty">Noch keine Kalender abonniert.</p>
        ) : (
          <ul className="list">
            {sources.map((source) => (
              <li key={source.id} className="card item">
                <div className="item-main">
                  <p className="item-title">
                    {source.name} <span className="badge">{ownerName(people, source.person_id)}</span>
                  </p>
                  <p className="item-meta">
                    {source.host} · {source.external ? 'ausserhalb des Heimnetzes' : 'im Heimnetz'}
                    {source.last_synced_at ? ` · abgeglichen ${clockTime(source.last_synced_at)}` : ''}
                  </p>
                  {source.last_error && <p className="item-meta">Fehler: {source.last_error}</p>}
                  {notice?.id === source.id && <p className="item-meta">{notice.text}</p>}
                </div>
                <div className="row">
                  {source.external && (
                    <label className="row">
                      <input
                        type="checkbox"
                        checked={source.allow_external}
                        onChange={(event) => void act(() => calendarApi.allowExternal(source.id, event.target.checked))}
                      />
                      <span>Externen Host erlauben</span>
                    </label>
                  )}
                  <button
                    type="button"
                    className="quiet"
                    disabled={source.external && !source.allow_external}
                    onClick={() =>
                      void act(async () =>
                        setNotice({ id: source.id, text: `${(await calendarApi.sync(source.id)).events} Termine gelesen.` }),
                      )
                    }
                  >
                    Abgleichen
                  </button>
                  <button type="button" className="danger" onClick={() => void act(() => calendarApi.deleteSource(source.id))}>
                    Entfernen
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <SourceForm people={people} onAdd={(personId, name, url) => act(() => calendarApi.addSource(personId, name, url))} />
        <p className="hint">
          Abonnierte Kalender sind nur lesbar. Pebbo verbindet sich nur mit dem Host in der Adresse: im Heimnetz
          sofort, ausserhalb erst, wenn du «Externen Host erlauben» einschaltest, und dann nur über https.
        </p>
      </section>
    </div>
  );
}

function OwnerSelect({ people, value, onChange }: { people: Person[]; value: string; onChange(value: string): void }) {
  return (
    <label className="field">
      <span>Für</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.name}
          </option>
        ))}
        <option value="household">Haushalt</option>
      </select>
    </label>
  );
}

const ownerId = (value: string): number | null => (value === 'household' ? null : Number(value));

function EventForm({ people, onAdd }: { people: Person[]; onAdd(personId: number | null, title: string, start: string): Promise<void> }) {
  const [owner, setOwner] = useState(String(people[0]?.id ?? 'household'));
  const [title, setTitle] = useState('');
  const [date, setDate] = useState(today());
  const [time, setTime] = useState('');

  function add(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !date) return;
    void onAdd(ownerId(owner), title.trim(), time ? `${date}T${time}` : date);
    setTitle('');
  }

  return (
    <form className="card form-row" onSubmit={add}>
      <OwnerSelect people={people} value={owner} onChange={setOwner} />
      <label className="field grow">
        <span>Neuer Termin</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} placeholder="z. B. Zahnarzt" />
      </label>
      <label className="field">
        <span>Datum</span>
        <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
      </label>
      <label className="field">
        <span>Zeit (leer: ganztägig)</span>
        <input type="time" value={time} onChange={(event) => setTime(event.target.value)} />
      </label>
      <button type="submit" className="primary" disabled={!title.trim() || !date}>
        Eintragen
      </button>
    </form>
  );
}

function SourceForm({ people, onAdd }: { people: Person[]; onAdd(personId: number | null, name: string, url: string): Promise<void> }) {
  const [owner, setOwner] = useState('household');
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');

  function add(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    void onAdd(ownerId(owner), name.trim(), url.trim());
    setName('');
    setUrl('');
  }

  return (
    <form className="card form-row" onSubmit={add}>
      <OwnerSelect people={people} value={owner} onChange={setOwner} />
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={60} placeholder="z. B. Schule" />
      </label>
      <label className="field grow">
        <span>ICS-Adresse</span>
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://… oder webcal://…" />
      </label>
      <button type="submit" className="primary" disabled={!url.trim()}>
        Abonnieren
      </button>
    </form>
  );
}
