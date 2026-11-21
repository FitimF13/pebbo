import { useCallback, useEffect, useState } from 'react';
import { pairingLink, type NewPhonePairing, type PhonesResponse } from '@pebbo/contracts';
import type { Person } from './api';
import { phonesApi } from './phonesApi';
import { QrCode } from './QrCode';

const REFRESH_MS = 3000;

/** Pair phones with a code and a QR code, and remove paired phones. */
export function Phones({ people }: { people: Person[] }) {
  const [data, setData] = useState<PhonesResponse>();
  const [pairing, setPairing] = useState<NewPhonePairing>();
  const [address, setAddress] = useState('');
  const [personId, setPersonId] = useState(people[0]?.id ?? 0);
  const [error, setError] = useState<string>();
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      setData(await phonesApi.list());
    } catch {
      setError('Die Handys konnten nicht geladen werden.');
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => {
      setNow(Date.now());
      void load();
    }, REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  // A pairing is over once it is no longer open: the phone used the code, or it expired.
  const open =
    pairing !== undefined &&
    pairing.expires_at * 1000 > now &&
    (data?.pairings.some((item) => item.id === pairing.id) ?? true);
  useEffect(() => {
    if (pairing && !open) setPairing(undefined);
  }, [pairing, open]);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Das hat nicht geklappt.');
    }
    await load();
  }

  function start() {
    void run(async () => {
      const created = await phonesApi.createPairing(personId);
      setPairing(created);
      setAddress(created.addresses[0] ?? '');
    });
  }

  function cancel(id: number) {
    void run(async () => {
      setPairing(undefined);
      await phonesApi.cancelPairing(id);
    });
  }

  const nameOf = (id: number) => people.find((person) => person.id === id)?.name ?? 'Unbekannt';
  const phones = data?.phones ?? [];

  return (
    <section className="group" aria-label="Handys">
      <h3>Handys</h3>
      {error && (
        <p className="control-error" role="alert">
          {error}
        </p>
      )}
      {phones.length === 0 ? (
        <p className="control-empty">Noch kein Handy gekoppelt.</p>
      ) : (
        <ul className="list" aria-label="Gekoppelte Handys">
          {phones.map((phone) => (
            <li key={phone.id} className="card item">
              <div className="item-main">
                <p className="item-title">
                  {phone.name} <span className="badge">{nameOf(phone.person_id)}</span>
                </p>
                <p className="item-meta">{phoneSeen(phone.last_seen_at)}</p>
              </div>
              <button type="button" className="danger" onClick={() => void run(() => phonesApi.remove(phone.id))}>
                Entkoppeln
              </button>
            </li>
          ))}
        </ul>
      )}

      {pairing && open ? (
        <div className="card pairing">
          <div className="pairing-qr">
            {address ? (
              <QrCode
                value={pairingLink({ address, code: pairing.code })}
                label={`QR-Code zum Koppeln für ${nameOf(pairing.person_id)}`}
              />
            ) : (
              <p className="control-empty">Keine Adresse im Heimnetz gefunden.</p>
            )}
          </div>
          <div className="pairing-info">
            <p>
              Handy von <strong>{nameOf(pairing.person_id)}</strong>: Scanne den QR-Code mit der Kamera des Handys oder
              gib in der Pebbo-App Adresse und Code ein.
            </p>
            <p className="pairing-code" aria-label="Kopplungscode">
              {pairing.code.slice(0, 3)} {pairing.code.slice(3)}
            </p>
            {pairing.addresses.length > 1 ? (
              <label className="field">
                <span>Adresse</span>
                <select value={address} onChange={(event) => setAddress(event.target.value)}>
                  {pairing.addresses.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="item-meta">Adresse: {address || 'unbekannt'}</p>
            )}
            {!pairing.reachable && (
              <p className="hint" role="note">
                Pebbo hört gerade nur auf diesem Computer. Starte ihn mit PEBBO_HOST=0.0.0.0, damit das Handy ihn im
                Heimnetz erreicht.
              </p>
            )}
            <p className="item-meta">Gültig noch {minutesLeft(pairing.expires_at, now)}. Der Code geht nur einmal.</p>
            <div className="row">
              <button type="button" className="quiet" onClick={() => cancel(pairing.id)}>
                Abbrechen
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="card form-row">
          <label className="field grow">
            <span>Handy koppeln für</span>
            <select value={personId} onChange={(event) => setPersonId(Number(event.target.value))}>
              {people.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="primary" disabled={!personId} onClick={start}>
            Code erstellen
          </button>
        </div>
      )}
      <p className="hint">
        Ein gekoppeltes Handy sieht nur die Erinnerungen und das Gedächtnis seiner Person und chattet als diese Person
        mit Pebbo. Entkoppeln wirkt sofort.
      </p>
    </section>
  );
}

function minutesLeft(expiresAt: number, now: number): string {
  const minutes = Math.max(0, Math.ceil((expiresAt * 1000 - now) / 60000));
  return minutes === 1 ? '1 Minute' : `${minutes} Minuten`;
}

function phoneSeen(lastSeen: number | null): string {
  if (!lastSeen) return 'Noch nie verbunden';
  const minutes = Math.round((Date.now() / 1000 - lastSeen) / 60);
  if (minutes < 2) return 'Gerade eben verbunden';
  if (minutes < 120) return `Vor ${minutes} Minuten verbunden`;
  return `Zuletzt verbunden am ${new Date(lastSeen * 1000).toLocaleDateString('de-CH')}`;
}
