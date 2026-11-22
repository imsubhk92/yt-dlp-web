import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  ExternalLink,
  Film,
  FolderArchive,
  HardDrive,
  Headphones,
  Link2,
  ListVideo,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api, bytes, duration } from "./api";
import ThemeControl from "./ThemeControl";
import {
  terminal,
  type Health,
  type Inspection,
  type Item,
  type Job,
  type Preset,
  type Resolution,
} from "./types";

const presets: {
  id: Preset;
  name: string;
  description: string;
  icon: typeof Film;
}[] = [
  {
    id: "mp4",
    name: "MP4 video",
    description: "Made for your devices",
    icon: Film,
  },
  {
    id: "best",
    name: "Best quality",
    description: "Original video & audio",
    icon: Zap,
  },
  {
    id: "mp3",
    name: "MP3 audio",
    description: "Just the good sound",
    icon: Headphones,
  },
];
const labels: Record<string, string> = {
  queued: "In queue",
  downloading: "Downloading",
  processing: "Merging / converting",
  completed: "Completed",
  partial: "Partially completed",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

function ItemRow({ item, jobId }: { item: Item; jobId: string }) {
  const percent =
    item.total_bytes && item.status === "downloading"
      ? Math.min(
          99,
          Math.round((item.downloaded_bytes / item.total_bytes) * 100),
        )
      : null;
  const working = ["downloading", "processing"].includes(item.status);
  return (
    <div className="job-item">
      <div
        className={`item-icon ${item.status === "completed" ? "success" : ""}`}
      >
        {item.status === "completed" ? (
          <Check size={16} />
        ) : working ? (
          <Loader2 size={16} className="spin" />
        ) : (
          <Film size={16} />
        )}
      </div>
      <div className="item-content">
        <div className="item-heading">
          <span title={item.title}>{item.title}</span>
          <small>
            {percent !== null ? `${percent}%` : labels[item.status]}
          </small>
        </div>
        {item.status === "downloading" && (
          <>
            <progress
              aria-label={`Download progress for ${item.title}`}
              max={100}
              value={percent ?? undefined}
            />
            <div className="transfer-meta">
              {bytes(item.downloaded_bytes)}
              {item.total_bytes ? ` / ${bytes(item.total_bytes)}` : ""}
              {item.speed ? ` · ${bytes(item.speed)}/s` : ""}
              {item.eta !== null ? ` · ${duration(item.eta)} remaining` : ""}
            </div>
          </>
        )}
        {item.status === "processing" && (
          <small className="muted">
            Finishing your file. This can take a moment.
          </small>
        )}
        {item.error && <p className="item-error">{item.error}</p>}
        {item.status === "completed" && (
          <small className="muted">
            {bytes(item.size)} · {item.filename}
          </small>
        )}
      </div>
      {item.file_id && (
        <a
          className="icon-button"
          aria-label={`Save ${item.title}`}
          title="Save file"
          href={`/api/jobs/${jobId}/files/${item.file_id}`}
        >
          <ArrowDownToLine size={17} />
        </a>
      )}
    </div>
  );
}

function JobCard({
  job,
  onAction,
}: {
  job: Job;
  onAction: (
    id: string,
    action: "cancel" | "retry" | "delete",
  ) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(!terminal.has(job.status));
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const retryable =
    terminal.has(job.status) &&
    job.items.some((i) =>
      ["failed", "cancelled", "interrupted"].includes(i.status),
    );
  async function action(kind: "cancel" | "retry" | "delete") {
    setBusy(true);
    try {
      await onAction(job.id, kind);
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  }
  return (
    <article className="job-card">
      <div className="job-top">
        <div className="job-type">
          {job.preset === "mp3" ? (
            <Headphones size={20} />
          ) : job.kind === "playlist" ? (
            <ListVideo size={21} />
          ) : (
            <Film size={20} />
          )}
        </div>
        <button
          className="job-title-button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          <strong>{job.title}</strong>
          <span>
            {job.preset === "mp3"
              ? "MP3 · 192 kbps"
              : `${job.preset === "mp4" ? "MP4" : "Original quality"} · ${job.resolution ? `${job.resolution}p max` : "Unrestricted"}`}
            <span className="dot">·</span>
            {job.completed_count}/{job.total_count} saved
          </span>
        </button>
        <span className={`status status-${job.status}`}>
          {!terminal.has(job.status) && <span className="live-dot" />}
          {labels[job.status]}
        </span>
        <button
          className={`icon-button expand ${expanded ? "expanded" : ""}`}
          aria-label={expanded ? "Collapse download" : "Expand download"}
          onClick={() => setExpanded(!expanded)}
        >
          <ChevronDown size={18} />
        </button>
      </div>
      {expanded && (
        <div className="job-items">
          {job.items.map((item) => (
            <ItemRow key={item.id} item={item} jobId={job.id} />
          ))}
        </div>
      )}
      <div className="job-footer">
        <span className="job-date">
          <Clock3 size={13} />
          {new Date(job.created_at).toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        <div className="job-actions">
          {job.archive_status === "ready" && (
            <a className="text-action" href={`/api/jobs/${job.id}/archive`}>
              <FolderArchive size={15} />
              Download ZIP
            </a>
          )}
          {job.archive_status === "building" && (
            <span className="muted building">
              <Loader2 size={14} className="spin" />
              Preparing ZIP
            </span>
          )}
          {retryable && (
            <button
              disabled={busy}
              className="text-action"
              onClick={() => action("retry")}
            >
              <RefreshCw size={14} />
              Retry unsuccessful
            </button>
          )}
          {!terminal.has(job.status) && (
            <button
              disabled={busy}
              className="text-action"
              onClick={() => action("cancel")}
            >
              <X size={15} />
              Cancel
            </button>
          )}
          <a
            className="icon-button"
            href={job.source_url}
            target="_blank"
            rel="noreferrer"
            aria-label="Open source"
          >
            <ExternalLink size={14} />
          </a>
          <button
            disabled={busy}
            className="icon-button danger"
            onClick={() => setConfirmDelete(true)}
            aria-label={`Delete ${job.title}`}
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>
      {job.archive_error && (
        <p className="archive-error" role="status">
          {job.archive_error}
        </p>
      )}
      {confirmDelete && (
        <div className="delete-confirm" role="alert">
          <span>Delete this download and its saved files?</span>
          <button
            className="text-action"
            disabled={busy}
            onClick={() => setConfirmDelete(false)}
          >
            Keep files
          </button>
          <button
            className="button danger-button"
            disabled={busy}
            onClick={() => action("delete")}
          >
            {busy ? "Deleting…" : "Delete files"}
          </button>
        </div>
      )}
    </article>
  );
}

export default function App() {
  const [view, setView] = useState<"download" | "library">("download");
  const [url, setUrl] = useState("");
  const [playlist, setPlaylist] = useState(false);
  const [preset, setPreset] = useState<Preset>("mp4");
  const [resolution, setResolution] = useState<Resolution>(1080);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [page, setPage] = useState(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState(false);
  const [busy, setBusy] = useState<"inspect" | "start" | null>(null);
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const requestVersion = useRef(0);

  const refresh = useCallback(async () => {
    const value = await api<Job[]>(`/jobs?limit=25&offset=${page * 25}`);
    setJobs(value);
    setConnectionError(false);
  }, [page]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<Job[]>(`/jobs?limit=25&offset=${page * 25}`);
        if (!disposed) {
          setJobs(value);
          setConnectionError(false);
        }
      } catch {
        if (!disposed) setConnectionError(true);
      }
      if (!disposed) timer = setTimeout(poll, 1000);
    }
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [page]);

  useEffect(() => {
    const check = () =>
      api<Health>("/health")
        .then(setHealth)
        .catch(() => setConnectionError(true));
    void check();
    const timer = setInterval(check, 30000);
    return () => clearInterval(timer);
  }, []);

  function invalidatePreview() {
    requestVersion.current += 1;
    setInspection(null);
    setSelected(new Set());
    setError("");
  }

  async function inspect(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy("inspect");
    const version = ++requestVersion.current;
    try {
      const result = await api<Inspection>("/inspect", {
        method: "POST",
        body: JSON.stringify({ url, playlist }),
      });
      if (version !== requestVersion.current) return;
      setInspection(result);
      setSelected(
        new Set(result.entries.filter((e) => e.available).map((e) => e.id)),
      );
    } catch (e) {
      if (version === requestVersion.current) setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function startDownload() {
    if (!inspection) return;
    setBusy("start");
    setError("");
    try {
      await api<Job>("/jobs", {
        method: "POST",
        body: JSON.stringify({
          inspection_id: inspection.id,
          entry_ids: [...selected],
          preset,
          resolution: preset === "mp3" ? null : resolution,
        }),
      });
      setPage(0);
      setInspection(null);
      setUrl("");
      setSelected(new Set());
      setNotice("Added to your downloads. You can keep adding links.");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function onAction(id: string, action: "cancel" | "retry" | "delete") {
    try {
      await api(action === "delete" ? `/jobs/${id}` : `/jobs/${id}/${action}`, {
        method: action === "delete" ? "DELETE" : "POST",
      });
      if (action === "retry") {
        setPage(0);
        setNotice("Unsuccessful items added as a new download.");
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const available = inspection?.entries.filter((e) => e.available) ?? [];
  const active = jobs.filter((j) => !terminal.has(j.status)).length;
  const saved = jobs.reduce((sum, job) => sum + job.completed_count, 0);
  return (
    <div className="app-shell">
      <header className="header">
        <div className="header-inner">
          <a className="brand" href="/" aria-label="Downstream home">
            <span className="brand-mark">
              <ArrowDownToLine size={22} strokeWidth={2.5} />
            </span>
            downstream<span className="brand-period">.</span>
          </a>
          <nav aria-label="Main navigation">
            <button
              className={
                view === "download" ? "nav-button selected" : "nav-button"
              }
              onClick={() => setView("download")}
            >
              <Plus size={16} />
              New download
            </button>
            <button
              className={
                view === "library" ? "nav-button selected" : "nav-button"
              }
              onClick={() => setView("library")}
            >
              <HardDrive size={16} />
              Library
              {jobs.length > 0 && (
                <span className="nav-count">
                  {jobs.length}
                  {jobs.length === 25 ? "+" : ""}
                </span>
              )}
            </button>
          </nav>
          <div className="header-actions">
            <div className="local-badge">
              <span className={health?.ready ? "live-dot green" : "live-dot"} />
              Running locally
            </div>
            <ThemeControl />
          </div>
        </div>
      </header>

      <main>
        <section className="intro">
          <div>
            <div className="eyebrow">
              <span />
              YOUR PERSONAL MEDIA SHELF
            </div>
            <h1>
              {view === "download" ? (
                <>
                  Your links.
                  <br />
                  <span>Your offline collection.</span>
                </>
              ) : (
                <>
                  The good stuff.
                  <br />
                  <span>Saved for later.</span>
                </>
              )}
            </h1>
            <p>
              Videos, playlists, or just the audio. Save what you love,
              <br className="desktop-break" /> and take it with you.
            </p>
          </div>
          <div className="intro-art" aria-hidden="true">
            <div className="art-orbit orbit-one" />
            <div className="art-orbit orbit-two" />
            <div className="floating-note">
              <Headphones size={22} />
            </div>
            <div className="art-card">
              <div className="art-card-top">
                <span />
                <span />
                <span />
              </div>
              <div className="art-play">
                <ArrowDown size={35} strokeWidth={2} />
              </div>
              <div className="art-line" />
              <div className="art-line short" />
            </div>
            <div className="floating-check">
              <Check size={19} />
            </div>
          </div>
        </section>

        {connectionError && (
          <div className="banner error" role="alert">
            Cannot reach the local server. Check that FastAPI is running.
          </div>
        )}
        {health && !health.ready && (
          <div className="banner warning" role="alert">
            <strong>A little setup is needed</strong>
            {health.issues.map((issue) => (
              <span key={issue}>{issue}</span>
            ))}
          </div>
        )}
        {error && (
          <div className="banner error" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={17} />
            </button>
          </div>
        )}
        {notice && (
          <div className="banner success-banner" role="status">
            <CheckCircle2 size={17} />
            <span>{notice}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {view === "download" && (
          <section
            className="download-card"
            aria-labelledby="new-download-title"
          >
            <div className="card-heading">
              <span className="section-icon">
                <Link2 size={18} />
              </span>
              <div>
                <h2 id="new-download-title">Start with a link</h2>
                <p>
                  Works with YouTube and thousands of yt-dlp supported sites.
                </p>
              </div>
              <span className="step-label">01 — ADD & CHOOSE</span>
            </div>
            <form onSubmit={inspect}>
              <label className="sr-only" htmlFor="video-url">
                Video or playlist URL
              </label>
              <div className="url-input-wrap">
                <Link2 size={19} />
                <input
                  ref={input}
                  id="video-url"
                  type="url"
                  required
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    invalidatePreview();
                  }}
                  placeholder="Paste a video or playlist link here…"
                  autoComplete="off"
                  disabled={busy === "start"}
                />
                <button
                  className="button primary inspect-button"
                  type="submit"
                  disabled={!!busy || !url.trim() || !health?.ready}
                >
                  {busy === "inspect" ? (
                    <>
                      <Loader2 size={17} className="spin" />
                      Inspecting…
                    </>
                  ) : (
                    <>
                      Find media
                      <ArrowRight size={17} />
                    </>
                  )}
                </button>
              </div>
              <div className="input-footer">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={playlist}
                    disabled={busy === "start"}
                    onChange={(e) => {
                      setPlaylist(e.target.checked);
                      invalidatePreview();
                    }}
                  />
                  Include playlist
                  <span className="muted optional-hint">
                    when your link contains both a video and a playlist
                  </span>
                </label>
              </div>
            </form>
            <div className="settings-row">
              <div className="format-settings">
                <div className="field-label">SAVE AS</div>
                <div
                  className="preset-grid"
                  role="radiogroup"
                  aria-label="Output format"
                >
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      role="radio"
                      aria-checked={preset === p.id}
                      className={`preset ${preset === p.id ? "chosen" : ""}`}
                      onClick={() => setPreset(p.id)}
                    >
                      <p.icon size={20} />
                      <span>
                        <strong>{p.name}</strong>
                        <small>{p.description}</small>
                      </span>
                      <span className="radio-dot">
                        {preset === p.id && <Check size={10} strokeWidth={3} />}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="quality-setting">
                <label className="field-label" htmlFor="quality">
                  {preset === "mp3" ? "AUDIO QUALITY" : "MAX VIDEO QUALITY"}
                </label>
                <div className="select-wrap">
                  <select
                    id="quality"
                    disabled={preset === "mp3"}
                    value={preset === "mp3" ? "audio" : (resolution ?? "best")}
                    onChange={(e) =>
                      setResolution(
                        e.target.value === "best"
                          ? null
                          : (Number(e.target.value) as Resolution),
                      )
                    }
                  >
                    {preset === "mp3" ? (
                      <option value="audio">192 kbps</option>
                    ) : (
                      <>
                        <option value={480}>480p</option>
                        <option value={720}>720p · HD</option>
                        <option value={1080}>1080p · Full HD</option>
                        <option value={1440}>1440p · QHD</option>
                        <option value={2160}>2160p · 4K</option>
                        <option value="best">Best available</option>
                      </>
                    )}
                  </select>
                  <ChevronDown size={16} />
                </div>
              </div>
            </div>
            {preset === "best" && (
              <p className="format-note">
                Keeps original codecs. Merged files use MKV; individual streams
                keep their source container.
              </p>
            )}
            {preset === "mp4" && (
              <p className="format-note">
                H.264 + AAC for broad compatibility. Availability depends on the
                source.
              </p>
            )}

            {inspection && (
              <div className="preview" data-testid="media-preview">
                <div className="preview-heading">
                  <div>
                    <div className="field-label">
                      {inspection.kind === "playlist"
                        ? "PLAYLIST PREVIEW"
                        : "VIDEO PREVIEW"}
                    </div>
                    <h3>{inspection.title}</h3>
                    <p>
                      {available.length} available{" "}
                      {available.length === 1 ? "item" : "items"} ·{" "}
                      {selected.size} selected
                    </p>
                  </div>
                  <button
                    className="icon-button"
                    aria-label="Close preview"
                    onClick={() => setInspection(null)}
                  >
                    <X size={18} />
                  </button>
                </div>
                {inspection.truncated && (
                  <div className="banner warning">
                    This preview is limited to the first {inspection.limit}{" "}
                    entries. Only those entries can be selected. Increase
                    YTDLP_PLAYLIST_LIMIT to inspect more.
                  </div>
                )}
                {inspection.kind === "playlist" && available.length > 0 && (
                  <label className="checkbox-label select-all">
                    <input
                      type="checkbox"
                      checked={selected.size === available.length}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? new Set(available.map((x) => x.id))
                            : new Set(),
                        )
                      }
                    />
                    Select all available
                  </label>
                )}
                <div className="preview-entries">
                  {inspection.entries.map((entry) => (
                    <label
                      className={`preview-entry ${!entry.available ? "unavailable" : ""}`}
                      key={entry.id}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select ${entry.title}`}
                        disabled={!entry.available}
                        checked={selected.has(entry.id)}
                        onChange={(e) =>
                          setSelected((current) => {
                            const next = new Set(current);
                            if (e.target.checked) next.add(entry.id);
                            else next.delete(entry.id);
                            return next;
                          })
                        }
                      />
                      <span className="entry-index">
                        {String(entry.position).padStart(2, "0")}
                      </span>
                      <span className="thumbnail">
                        {entry.thumbnail?.startsWith("https://") ? (
                          <img
                            loading="lazy"
                            src={entry.thumbnail}
                            referrerPolicy="no-referrer"
                            alt=""
                          />
                        ) : (
                          <Film size={20} />
                        )}
                      </span>
                      <span className="entry-title">
                        {entry.title}
                        <small>
                          {entry.available
                            ? duration(entry.duration)
                            : "Unavailable"}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
                {!available.length && (
                  <p className="empty-preview">
                    No available videos were found in this link.
                  </p>
                )}
                <div className="preview-bottom">
                  <span>
                    <HardDrive size={15} />
                    Saved on this computer
                  </span>
                  <button
                    className="button primary"
                    disabled={!selected.size || !!busy || !health?.ready}
                    onClick={startDownload}
                  >
                    {busy === "start" ? (
                      <Loader2 size={17} className="spin" />
                    ) : (
                      <Download size={17} />
                    )}
                    Download{" "}
                    {selected.size > 1
                      ? `${selected.size} items`
                      : preset === "mp3"
                        ? "audio"
                        : "video"}
                  </button>
                </div>
              </div>
            )}
            <div className="card-footnote">
              <ShieldCheck size={14} />
              Your downloads stay on your computer.
              <span className="dot">·</span>
              {health?.cookie_configured
                ? "Local cookie file configured"
                : "No account needed"}
            </div>
          </section>
        )}

        <section className="library" aria-labelledby="library-title">
          <div className="library-heading">
            <div>
              <div className="section-title">
                <h2 id="library-title">
                  {view === "library" ? "Your library" : "Your downloads"}
                </h2>
                <span className="count-badge">{jobs.length}</span>
              </div>
              <p>
                {active
                  ? `${active} ${active === 1 ? "download" : "downloads"} in progress. We'll take it from here.`
                  : "A little collection of things worth keeping."}
              </p>
            </div>
            <div className="library-meta">
              {saved > 0 && (
                <span>
                  <CheckCircle2 size={14} />
                  {saved} {saved === 1 ? "file" : "files"} on this page
                </span>
              )}
              <button
                className="icon-button"
                aria-label="Refresh downloads"
                onClick={() => refresh().catch(() => setConnectionError(true))}
              >
                <RefreshCw size={16} />
              </button>
            </div>
          </div>
          {jobs.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <ArrowDownToLine size={25} />
              </div>
              <h3>
                {page ? "No more downloads" : "Your collection starts here"}
              </h3>
              <p>
                {page
                  ? "Go back to see your saved downloads."
                  : "Paste a link above. Your videos and audio will appear here."}
              </p>
              {view === "library" && !page && (
                <button
                  className="text-action"
                  onClick={() => {
                    setView("download");
                    setTimeout(() => input.current?.focus(), 0);
                  }}
                >
                  Add your first download
                  <ArrowRight size={15} />
                </button>
              )}
            </div>
          ) : (
            <div className="jobs-list">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} onAction={onAction} />
              ))}
            </div>
          )}
          {(page > 0 || jobs.length === 25) && (
            <div className="pagination">
              <button
                className="button secondary"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                Newer
              </button>
              <span>Page {page + 1}</span>
              <button
                className="button secondary"
                disabled={jobs.length < 25}
                onClick={() => setPage((p) => p + 1)}
              >
                Older
              </button>
            </div>
          )}
        </section>
        <footer className="footer">
          <span>
            downstream<span className="brand-period">.</span>
            <span className="footer-caption">
              A home for your offline favorites.
            </span>
          </span>
          <span>
            Powered by yt-dlp <span className="dot">·</span>
            <a href="/docs" target="_blank" rel="noreferrer">
              API docs
              <ExternalLink size={11} />
            </a>
          </span>
        </footer>
      </main>
    </div>
  );
}
