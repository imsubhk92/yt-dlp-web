export type Preset = "mp4" | "best" | "mp3";
export type Resolution = 480 | 720 | 1080 | 1440 | 2160 | null;
export type Status =
  | "queued"
  | "downloading"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "interrupted";
export type Entry = {
  id: string;
  position: number;
  title: string;
  url: string | null;
  duration: number | null;
  thumbnail: string | null;
  available: boolean;
};
export type Inspection = {
  id: string;
  source_url: string;
  title: string;
  kind: "video" | "playlist";
  entries: Entry[];
  truncated: boolean;
  limit: number;
};
export type Item = {
  id: string;
  position: number;
  title: string;
  status: Status;
  downloaded_bytes: number;
  total_bytes: number | null;
  speed: number | null;
  eta: number | null;
  error: string | null;
  file_id: string | null;
  filename: string | null;
  size: number | null;
};
export type Job = {
  id: string;
  title: string;
  source_url: string;
  kind: "video" | "playlist";
  preset: Preset;
  resolution: Resolution;
  status: Status;
  created_at: string;
  completed_count: number;
  total_count: number;
  archive_status: "none" | "building" | "ready" | "failed";
  archive_error: string | null;
  items: Item[];
};
export type Health = {
  ready: boolean;
  dependencies: Record<string, boolean>;
  issues: string[];
  cookie_configured: boolean;
};
export const terminal = new Set<Status>([
  "completed",
  "partial",
  "failed",
  "cancelled",
  "interrupted",
]);
