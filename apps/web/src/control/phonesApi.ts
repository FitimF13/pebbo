/** Control centre API for paired phones (see core/src/pebbo/phones.py). */
import type { NewPhonePairing, PhonesResponse } from '@pebbo/contracts';
import { request, send } from './api';

export const phonesApi = {
  list: () => request<PhonesResponse>('/phones'),
  createPairing: (personId: number) =>
    request<NewPhonePairing>('/phones/pairings', send('POST', { person_id: personId })),
  cancelPairing: (id: number) => request<void>(`/phones/pairings/${id}`, send('DELETE')),
  remove: (id: number) => request<void>(`/phones/${id}`, send('DELETE')),
};
