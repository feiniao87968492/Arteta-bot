export type ApiResponse<T> = {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
};

export type StatusCardState = 'ok' | 'warn' | 'error' | 'idle';
