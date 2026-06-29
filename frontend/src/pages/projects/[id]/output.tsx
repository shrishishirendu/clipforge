import { useRouter } from "next/router";
import { useCallback, useEffect, useState } from "react";

import Topbar from "@/components/Topbar";
import { ApiError, OutputOut, api } from "@/lib/api";

export default function Output() {
  const router = useRouter();
  const pid = router.query.id as string | undefined;
  const [out, setOut] = useState<OutputOut | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    if (!pid) return;
    try {
      setOut(await api.getOutput(pid));
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 404) { router.replace(`/projects/${pid}/processing`); return; }
      setError(e?.message || "Could not load output");
    }
  }, [pid, router]);

  useEffect(() => { load(); }, [load]);

  function copy(url: string) {
    navigator.clipboard?.writeText(url).then(() => { setToast("Link copied"); setTimeout(() => setToast(""), 2000); });
  }

  if (error) return (<><Topbar /><main className="page"><div className="container"><div className="banner banner-fail">⚠ {error}</div></div></main></>);
  if (!out) return (<><Topbar /><main className="page"><div className="center-screen"><span className="spinner spinner-burgundy" /></div></main></>);

  const sizeMb = (out.size_bytes / 1048576).toFixed(1);

  return (
    <>
      <Topbar />
      <main className="page">
        <div className="container" style={{ maxWidth: 820 }}>
          <span className="badge badge-ok"><span className="dot" /> Cut approved &amp; rendered</span>
          <h1 className="page-title" style={{ marginTop: 14 }}>Your cut is ready</h1>
          <p className="page-sub">The approved 3–4 minute cut, with sidecar captions. Download, copy a link, or start a new summary.</p>

          <div className="card" style={{ marginTop: 24, overflow: "hidden" }}>
            {out.video_url && (
              <video controls src={out.video_url} style={{ width: "100%", display: "block", background: "#000", maxHeight: 460 }} />
            )}
            <div className="card-pad between" style={{ borderTop: "1px solid var(--line)" }}>
              <div>
                <div style={{ fontWeight: 600 }}>cut.mp4</div>
                <div className="hint">{out.resolution} · {sizeMb} MB · with .srt captions</div>
              </div>
              <div className="row">
                {out.video_url && <a className="btn btn-primary" href={out.video_url} download="cut.mp4">⬇ Download MP4</a>}
                {out.captions_url && <a className="btn btn-ghost" href={out.captions_url} download="cut.srt">⬇ SRT</a>}
                {out.video_url && <button className="btn btn-ghost" onClick={() => copy(out.video_url!)}>🔗 Copy link</button>}
              </div>
            </div>
          </div>

          <div className="between" style={{ marginTop: 26 }}>
            <span className="hint">Need a different cut? Start again with the same or new material.</span>
            <button className="btn btn-ghost" onClick={() => router.push("/")}>+ New summary</button>
          </div>
        </div>
      </main>
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
