/** Response of the core's `GET /health` endpoint. */
export interface HealthResponse {
  status: 'ok';
  version: string;
}

export * from './face';
export * from './phone';
