import { useRouter } from "next/router";
import { useRef, useState } from "react";

import Topbar from "@/components/Topbar";
import { AssetType, api } from "@/lib/api";

const SPEC: Record<AssetType, { title: string; hint: string; accept: string; exts: string[]; icon: string }> = {
  video: { title: "Video", hint: "The full talk — MP4 or MOV", accept: ".mp4,.mov,video/mp4,video/quicktime", exts: ["mp4", "mov"], icon: "🎬" },
  deck: { title: "Presentation deck", hint: "Slides — PPTX or PDF", accept: ".pptx,.pdf", exts: ["pptx", "pdf"], icon: "📊" },
  summary: { title: "Summary / key points", hint: "DOCX, PDF or TXT", accept: ".docx,.pdf,.txt", exts: ["docx", "pdf", "txt"], icon: "📝" },
};
const ORDER: AssetType[] = ["video", "deck", "summary"];
const ext = (n: string) => (n.includes(".") ? n.split(".").pop()!.toLowerCase() : "");

function Dropzone({ type, file, onPick }: { type: AssetType; file: File | null; onPick: (f: File | null) => void }) {
  const spec = SPEC[type];
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [err, setErr] = useState("");

  const accept = (f: File | null) => {
    if (!f) return;
    if (!spec.exts.includes(ext(f.name))) {
      setErr(`Must be ${spec.exts.map((e) => "." + e).join(" / ")}`);
      return;
    }
    setErr("");
    onPick(f);
  };

  return (
    <div>
      <div
        className={`dropzone${file ? " filled" : ""}${drag ? " dragover" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); accept(e.dataTransfer.files?.[0] ?? null); }}
      >
        <div className="dz-icon">{file ? "✓" : spec.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="dz-title">{spec.title}</div>
          <div className="dz-meta" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {file ? `${file.name} · ${(file.size / 1048576).toFixed(1)} MB` : spec.hint}
          </div>
        </div>
        {file && (
          <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); onPick(null); }}>
            Replace
          </button>
        )}
        <input
          ref={inputRef} type="file" accept={spec.accept} style={{ display: "none" }}
          onChange={(e) => accept(e.target.files?.[0] ?? null)}
        />
      </div>
      {err && <div className="hint" style={{ color: "var(--fail)", marginTop: 6 }}>{err}</div>}
    </div>
  );
}

export default function Upload() {
  const router = useRouter();
  const [files, setFiles] = useState<Record<AssetType, File | null>>({ video: null, deck: null, summary: null });
  const [title, setTitle] = useState("");
  const [minMin, setMinMin] = useState(3);
  const [maxMin, setMaxMin] = useState(4);
  const [vocab, setVocab] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const ready = ORDER.every((t) => files[t]) && minMin <= maxMin && minMin > 0;

  const pick = (t: AssetType) => (f: File | null) => {
    setFiles((s) => ({ ...s, [t]: f }));
    if (t === "video" && f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };

  async function submit() {
    setError(""); setBusy(true);
    try {
      setStep("Creating project…");
      const vocabulary = vocab.split(",").map((v) => v.trim()).filter(Boolean);
      const project = await api.createProject({
        title: title || "Untitled",
        target_min_sec: minMin * 60,
        target_max_sec: maxMin * 60,
        vocabulary,
      });
      for (const type of ORDER) {
        const file = files[type]!;
        setStep(`Uploading ${SPEC[type].title.toLowerCase()}…`); setProgress(0);
        const up = await api.requestUpload(project.id, type, file.name);
        await api.uploadToStorage(up.upload_url, file, setProgress);
        await api.completeAsset(project.id, up.asset_id);
      }
      setStep("Starting…");
      await api.start(project.id);
      router.push(`/projects/${project.id}/processing`);
    } catch (e: any) {
      setError(e?.message || "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <>
      <Topbar />
      <main className="page">
        <div className="container">
          <h1 className="page-title">New summary</h1>
          <p className="page-sub">
            Add the full talk, its deck and a summary document. We&apos;ll transcribe the
            video, use the deck and summary as the editorial guide, and propose a tight
            3–4 minute cut for you to review before anything renders.
          </p>

          <div className="card card-pad stack" style={{ marginTop: 28 }}>
            {ORDER.map((t) => (
              <Dropzone key={t} type={t} file={files[t]} onPick={pick(t)} />
            ))}
          </div>

          <div className="card card-pad stack" style={{ marginTop: 20 }}>
            <div>
              <label className="field-label">Project title</label>
              <input type="text" value={title} placeholder="e.g. Q3 Engineering All-Hands"
                     onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="grid-2" style={{ gridTemplateColumns: "1fr 1fr", gap: 20 }}>
              <div>
                <label className="field-label">Target length</label>
                <div className="row">
                  <input type="number" min={1} max={30} value={minMin} style={{ width: 80 }}
                         onChange={(e) => setMinMin(Number(e.target.value))} />
                  <span className="muted">to</span>
                  <input type="number" min={1} max={30} value={maxMin} style={{ width: 80 }}
                         onChange={(e) => setMaxMin(Number(e.target.value))} />
                  <span className="muted">minutes</span>
                </div>
              </div>
              <div>
                <label className="field-label">Custom vocabulary <span className="muted">(optional)</span></label>
                <input type="text" value={vocab} placeholder="names, product terms — comma separated"
                       onChange={(e) => setVocab(e.target.value)} />
              </div>
            </div>
          </div>

          {error && <div className="banner banner-fail" style={{ marginTop: 20 }}>⚠ {error}</div>}

          <div className="between" style={{ marginTop: 24 }}>
            <div className="hint">
              {busy ? step : ready ? "Ready to generate." : "Add all three files to continue."}
            </div>
            <button className="btn btn-primary btn-lg" disabled={!ready || busy} onClick={submit}>
              {busy ? <><span className="spinner" /> {step || "Working…"}</> : "Generate cut →"}
            </button>
          </div>
          {busy && progress > 0 && progress < 100 && (
            <div className="progress-track" style={{ marginTop: 14 }}>
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>
      </main>
    </>
  );
}
