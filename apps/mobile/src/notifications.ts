/**
 * Due reminders while the app is open. The app asks the core every few seconds, shows what
 * is due and acknowledges it. Push notifications while the app is closed need the push
 * gateway, which is not built yet (see docs/phone.md).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import * as Haptics from 'expo-haptics';
import type { AppNotification } from '@pebbo/contracts';
import { ApiError, type AppClient } from './api/client';
import { acknowledgedUntil } from './pending';

export const POLL_MS = 15_000;

export function usePendingNotifications(client: AppClient, onUnpaired: (error: unknown) => void) {
  const [pending, setPending] = useState<AppNotification[]>([]);
  const known = useRef(new Set<number>());

  const poll = useCallback(async () => {
    try {
      const due = await client.notifications();
      if (due.some((n) => !known.current.has(n.id))) {
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      }
      known.current = new Set(due.map((n) => n.id));
      setPending(due);
    } catch (error) {
      if (error instanceof ApiError && error.unpaired) onUnpaired(error);
    }
  }, [client, onUnpaired]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      void poll();
      timer ??= setInterval(() => void poll(), POLL_MS);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = undefined;
    };
    if (AppState.currentState === 'active') start();
    const subscription = AppState.addEventListener('change', (state) => (state === 'active' ? start() : stop()));
    return () => {
      stop();
      subscription.remove();
    };
  }, [poll]);

  const acknowledge = useCallback(async () => {
    const until = acknowledgedUntil(pending);
    if (until === undefined) return;
    setPending([]);
    try {
      await client.acknowledge(until);
    } catch (error) {
      if (error instanceof ApiError && error.unpaired) onUnpaired(error);
    }
  }, [client, pending, onUnpaired]);

  return { pending, acknowledge };
}
