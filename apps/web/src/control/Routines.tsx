import { useCallback, useEffect, useState } from 'react';
import type { Person } from './api';
import { RUN_RESULTS, routinesApi, type Routine, type RoutineRun } from './routinesApi';

const REFRESH_MS = 4000;

function statusText(routine: Routine): string {
  if (routine.status === 'active') return 'Aktiv';
  if (routine.status === 'paused') return 'Pausiert';
  return routine.waiting_for_owner ? 'Wartet auf Freigabe' : 'Entwurf';
}

function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString('de-CH', { dateStyle: 'short', timeStyle: 'short' });
}

/** Routines taught by talking to Pebbo: pause, resume, approve, try, delete and the run log. */
export function Routines({ people }: { people: Person[] }) {
  const [routines, setRoutines] = useState<Routine[]>();
  const [runs, setRuns] = useState<RoutineRun[]>([]);
  const [open, setOpen] = useState<number>();
  const [tried, setTried] = useState<{ id: number; say: string }>();
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const [list, log] = await Promise.all([routinesApi.routines(), routinesApi.runs()]);
      setRoutines(list);
      setRuns(log);
    } catch {
      setError('Die Routinen können gerade nicht geladen werden.');
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

  if (!routines) return <p className="control-empty">Lädt …</p>;

  return (
    <div className="stack">
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      {routines.length === 0 ? (
        <p className="control-empty">
          Noch keine Routinen. Sag zum Beispiel «Pebbo, jeden Werktag um sieben sagst du mir guten Morgen».
        </p>
      ) : (
        <ul className="list" aria-label="Routinen">
          {routines.map((routine) => {
            const owner = people.find((person) => person.id === routine.person_id)?.name ?? 'Unbekannt';
            const log = runs.filter((run) => run.routine_id === routine.id);
            return (
              <li key={routine.id} className="card item routine">
                <div className="item-main">
                  <p className="item-title">
                    {routine.name} <span className={routine.status === 'active' ? 'badge online' : 'badge'}>{statusText(routine)}</span>
                  </p>
                  <p>{routine.description}</p>
                  <p className="item-meta">
                    {owner}
                    {routine.needs_owner && ' · braucht die Freigabe des Besitzers'}
                    {routine.last_run_at ? ` · zuletzt ${when(routine.last_run_at)}` : ''}
                  </p>
                  {tried?.id === routine.id && <p className="item-meta">{tried.say}</p>}
                  {open === routine.id && <RunLog runs={log} />}
                </div>
                <div className="row">
                  {routine.waiting_for_owner && (
                    <button type="button" className="primary" onClick={() => void act(() => routinesApi.setStatus(routine.id, 'active'))}>
                      Freigeben
                    </button>
                  )}
                  {routine.status === 'active' && (
                    <button type="button" className="quiet" onClick={() => void act(() => routinesApi.setStatus(routine.id, 'paused'))}>
                      Pausieren
                    </button>
                  )}
                  {routine.status === 'paused' && (
                    <button type="button" className="quiet" onClick={() => void act(() => routinesApi.setStatus(routine.id, 'active'))}>
                      Fortsetzen
                    </button>
                  )}
                  <button
                    type="button"
                    className="quiet"
                    onClick={() =>
                      void act(async () => setTried({ id: routine.id, say: (await routinesApi.test(routine.id)).say }))
                    }
                  >
                    Testen
                  </button>
                  <button
                    type="button"
                    className="quiet"
                    aria-expanded={open === routine.id}
                    onClick={() => setOpen(open === routine.id ? undefined : routine.id)}
                  >
                    Verlauf
                  </button>
                  <button type="button" className="danger" onClick={() => void act(() => routinesApi.remove(routine.id))}>
                    Löschen
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="hint">
        Routinen bringst du Pebbo im Gespräch bei, zum Beispiel «Wenn ich gehe und niemand mehr da ist, sag mir
        tschüss». Pebbo liest sie vor und speichert sie erst nach deinem Ja. Routinen, die andere betreffen,
        gelten erst nach der Freigabe hier. «Testen» zeigt nur, was die Routine tun würde.
      </p>
    </div>
  );
}

function RunLog({ runs }: { runs: RoutineRun[] }) {
  if (runs.length === 0) return <p className="item-meta">Noch nie gelaufen.</p>;
  return (
    <ul className="run-log" aria-label="Verlauf">
      {runs.slice(0, 10).map((run) => (
        <li key={run.id}>
          <p className="item-meta">
            {when(run.started_at)} · {run.trigger} · <strong>{RUN_RESULTS[run.result]}</strong>
          </p>
          {[...run.conditions.map((step) => ({ ...step, kind: 'Bedingung' })), ...run.actions.map((step) => ({ ...step, kind: 'Aktion' }))].map(
            (step, index) => (
              <p key={index} className="item-meta">
                {step.ok ? '✓' : '✗'} {step.kind}: {step.text}
                {step.outcome && step.outcome !== 'would' ? ` (${step.outcome})` : ''}
              </p>
            ),
          )}
        </li>
      ))}
    </ul>
  );
}
