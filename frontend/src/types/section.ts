export type SectionStatus = "idle" | "loading" | "ok" | "cached" | "error";

export interface SectionError {
  reason: string;
  detail: string;
  section: string;
  retryable: boolean;
  suggestion_key: string;
}

export interface SectionState<T = any> {
  status: SectionStatus;
  data: T | null;
  error?: SectionError;
  updatedAt?: string | null;
}
