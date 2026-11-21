/** Client for the routine endpoints of the control centre API. */
import { request, send } from './api';

export type RoutineStatus = 'draft' | 'active' | 'paused';

export interface Routine {
  id: number;
  person_id: number;
  name: string;
  text: string;
  /** The routine read back in German, as Pebbo says it. */
  description: string;
  status: RoutineStatus;
  waiting_for_owner: boolean;
  needs_owner: boolean;
  cooldown_minutes: number;
  daily_limit: number;
  created_at: number;
  last_run_at: number | null;
}

export interface RoutineStep {
  text: string;
  ok: boolean;
  outcome?: string;
}

export interface RoutineRun {
  id: number;
  routine_id: number;
  started_at: number;
  trigger: string;
  conditions: RoutineStep[];
  actions: RoutineStep[];
  result: 'done' | 'partial' | 'failed' | 'skipped' | 'cooldown' | 'limit' | 'test';
  dry_run: boolean;
}

export const RUN_RESULTS: Record<RoutineRun['result'], string> = {
  done: 'Ausgeführt',
  partial: 'Teilweise ausgeführt',
  failed: 'Fehlgeschlagen',
  skipped: 'Bedingung nicht erfüllt',
  cooldown: 'Zu kurz nach dem letzten Lauf',
  limit: 'Tageslimit erreicht',
  test: 'Probelauf',
};

export const routinesApi = {
  routines: () => request<Routine[]>('/routines'),
  setStatus: (id: number, status: 'active' | 'paused') =>
    request<Routine>(`/routines/${id}/status`, send('POST', { status })),
  test: (id: number) => request<{ say: string; run: RoutineRun }>(`/routines/${id}/test`, send('POST')),
  remove: (id: number) => request<void>(`/routines/${id}`, send('DELETE')),
  runs: (routineId?: number) =>
    request<RoutineRun[]>(routineId === undefined ? '/routine-runs' : `/routine-runs?routine_id=${routineId}`),
};
