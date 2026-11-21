import { createContext, useContext } from 'react';
import type { AppClient } from './api/client';
import type { Credentials } from './pairing';

export interface Session {
  credentials: Credentials;
  client: AppClient;
  /** Unpair on purpose, from the settings. */
  unpair(): Promise<void>;
  /** Turn an error into a message. If the core removed this phone, the app returns to pairing. */
  explain(error: unknown): string;
}

export const SessionContext = createContext<Session | undefined>(undefined);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession needs a paired phone.');
  return session;
}
