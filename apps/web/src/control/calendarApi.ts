/** Client for the calendar endpoints of the control centre API. */
import { request, send } from './api';

export interface CalendarOccurrence {
  event_id: number;
  person_id: number | null;
  source_id: number | null;
  title: string;
  start: number;
  end: number | null;
  all_day: boolean;
  recurring: boolean;
}

export interface CalendarSource {
  id: number;
  person_id: number | null;
  name: string;
  /** Only the host: the full address can contain a secret. */
  host: string;
  /** The host is outside the home network and needs the owner's permission. */
  external: boolean;
  allow_external: boolean;
  last_synced_at: number | null;
  last_error: string | null;
}

export const calendarApi = {
  events: (days = 14) => request<CalendarOccurrence[]>(`/calendar/events?days=${days}`),
  addEvent: (personId: number | null, title: string, start: string, end?: string) =>
    request<CalendarOccurrence>('/calendar/events', send('POST', { person_id: personId, title, start, end })),
  deleteEvent: (id: number) => request<void>(`/calendar/events/${id}`, send('DELETE')),
  sources: () => request<CalendarSource[]>('/calendar/sources'),
  addSource: (personId: number | null, name: string, url: string) =>
    request<CalendarSource>('/calendar/sources', send('POST', { person_id: personId, name, url })),
  allowExternal: (id: number, allowed: boolean) =>
    request<CalendarSource>(`/calendar/sources/${id}`, send('PATCH', { allow_external: allowed })),
  sync: (id: number) => request<{ events: number }>(`/calendar/sources/${id}/sync`, send('POST')),
  deleteSource: (id: number) => request<void>(`/calendar/sources/${id}`, send('DELETE')),
};
