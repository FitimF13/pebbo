import { useCallback } from 'react';
import type { AppReminder } from '@pebbo/contracts';
import { useSession } from '../session';
import { ListScreen } from './ListScreen';

export function RemindersScreen() {
  const { client } = useSession();
  const load = useCallback(() => client.reminders(), [client]);
  return (
    <ListScreen<AppReminder>
      load={load}
      toItem={(reminder) => ({ id: reminder.id, title: reminder.text, meta: reminder.due_text })}
      remove={(reminder) => client.cancelReminder(reminder.id)}
      removeLabel="Absagen"
      confirm="Erinnerung absagen?"
      empty="Keine offenen Erinnerungen. Schreib Pebbo zum Beispiel «Erinnere mich morgen um acht ans Paket»."
    />
  );
}
