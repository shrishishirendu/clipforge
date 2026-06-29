// Typed client for the ClipForge backend API (architecture §7).
const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

export type AssetType = "video" | "deck" | "summary";

export interface ProjectOut { id: string; title: string; status: string; }
export interface AssetUploadResponse {
  asset_id: string; type: string; storage_uri: string; upload_url: string; expires_in: number;
}
export interface AssetOut {
  id: string; project_id: string; type: string; status: string;
  format: string; size_bytes: number; storage_uri: string;
}
export interface StageState { name: string; state: "pending" | "running" | "done" | "failed"; pct: number; }
export interface StatusOut { project_id: string; status: string; stages: StageState[]; }
export interface SegmentOut {
  id: string; order: number; start_sec: number; end_sec: number;
  transcript_snippet: string; confidence: number; key_point_id: string | null; locked: boolean;
}
export interface KeyPointOut { id: string; text: string; source: string; }
export interface ClipListOut {
  id: string; total_duration_sec: number; target_min_sec: number; target_max_sec: number;
  approval_status: string; uncovered_key_point_ids: string[];
  key_points: KeyPointOut[]; segments: SegmentOut[];
}
export interface OutputOut {
  project_id: string; status: string; resolution: string; size_bytes: number;
  video_url: string | null; captions_url: string | null;
}
export interface SegmentEdit {
  segment_id: string; order?: number; start_sec?: number; end_sec?: number;
  locked?: boolean; remove?: boolean;
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : (detail?.message || `HTTP ${status}`));
    this.status = status;
    this.detail = detail;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail: any = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-json */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  createProject: (body: { title: string; target_min_sec?: number; target_max_sec?: number; vocabulary?: string[] }) =>
    req<ProjectOut>("/projects", { method: "POST", body: JSON.stringify(body) }),

  requestUpload: (pid: string, type: AssetType, filename: string) =>
    req<AssetUploadResponse>(`/projects/${pid}/assets`, {
      method: "POST", body: JSON.stringify({ type, filename }),
    }),

  // Direct PUT to object storage (presigned URL) — bypasses the app tier.
  async uploadToStorage(uploadUrl: string, file: File, onProgress?: (pct: number) => void) {
    await new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", uploadUrl);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, "upload to storage failed")));
      xhr.onerror = () => reject(new ApiError(0, "network error uploading to storage"));
      xhr.send(file);
    });
  },

  completeAsset: (pid: string, assetId: string) =>
    req<AssetOut>(`/projects/${pid}/assets/${assetId}/complete`, { method: "POST" }),

  start: (pid: string) => req<any>(`/projects/${pid}/start`, { method: "POST" }),

  getStatus: (pid: string) => req<StatusOut>(`/projects/${pid}/status`),

  getClipList: (pid: string) => req<ClipListOut>(`/projects/${pid}/cliplist`),

  patchClipList: (pid: string, edits: SegmentEdit[]) =>
    req<ClipListOut>(`/projects/${pid}/cliplist`, { method: "PATCH", body: JSON.stringify({ edits }) }),

  reedit: (pid: string) => req<any>(`/projects/${pid}/reedit`, { method: "POST" }),

  approve: (pid: string, confirmGaps = false) =>
    req<any>(`/projects/${pid}/approve`, { method: "POST", body: JSON.stringify({ confirm_gaps: confirmGaps }) }),

  getOutput: (pid: string) => req<OutputOut>(`/projects/${pid}/output`),
};

export function fmtTime(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}
