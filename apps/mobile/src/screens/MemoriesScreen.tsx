import { useCallback } from 'react';
import type { AppMemory } from '@pebbo/contracts';
import { Muted } from '../components/ui';
import { useSession } from '../session';
import { ListScreen } from './ListScreen';

function origin(memory: AppMemory): string {
  if (memory.kind === 'summary') return 'Gesprächszusammenfassung';
  if (memory.source === 'learned') return 'Nebenbei gelernt';
  if (memory.source === 'control centre') return 'Im Kontrollzentrum eingetragen';
  return 'Du hast es Pebbo gesagt';
}

export function MemoriesScreen() {
  const { client } = useSession();
  const load = useCallback(() => client.memories(), [client]);
  return (
    <ListScreen<AppMemory>
      load={load}
      toItem={(memory) => ({ id: memory.id, title: memory.text, meta: origin(memory) })}
      remove={(memory) => client.deleteMemory(memory.id)}
      removeLabel="Löschen"
      confirm="Das soll Pebbo vergessen?"
      empty="Pebbo weiss noch nichts über dich. Erzähl ihm etwas, zum Beispiel «Merk dir, ich trinke Kaffee ohne Zucker»."
      header={<Muted>Was Pebbo über dich weiss. Nur du siehst das hier.</Muted>}
    />
  );
}
