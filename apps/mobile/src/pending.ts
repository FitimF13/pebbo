/** Which due reminders the app has shown. */
import type { AppNotification } from '@pebbo/contracts';

/** The time up to which everything shown can be acknowledged, or `undefined` if nothing is shown. */
export function acknowledgedUntil(notifications: AppNotification[]): number | undefined {
  return notifications.reduce<number | undefined>(
    (latest, notification) => (latest === undefined || notification.due_at > latest ? notification.due_at : latest),
    undefined,
  );
}
