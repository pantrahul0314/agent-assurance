export const TOKENS = {
  "Org A editor": "org-a-editor-token",
  "Org A viewer": "org-a-viewer-token",
  "Org B editor": "org-b-editor-token",
} as const;

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export type Project = {
  id: string;
  name: string;
  status: string;
  export_mode: string;
  owner: string;
};

export type Environment = {
  id: string;
  project_id: string;
  local_alias: string;
  permitted_scope: string[];
  export_mode: string;
};

export type Run = {
  id: string;
  project_id: string;
  suite_digest: string;
  target_build: string | null;
  execution_status: string;
  gate: { status: string; reason: string };
  verdict_counts: Record<string, number>;
  attempt_count: number;
  created_at: string;
};

export type Finding = {
  id: string;
  case_id: string;
  invariant: string;
  severity: string;
  title: string;
  disposition: string;
  evidence_scope: string;
  first_seen_run_id: string;
  last_seen_run_id: string;
  fix_notes: string;
};
