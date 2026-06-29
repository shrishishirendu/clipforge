import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";

import Topbar from "@/components/Topbar";
import { StageState, StatusOut, api } from "@/lib/api";

const STAGE_LABEL: Record<string, string> = {
  transcription: "Transcribe the talk",
  extraction: "Extract key points from deck & summary",
  selection: "Select the best segments (AI)",
  review: "Human review & approval",
  render: "Render the final cut",
};

function StepIcon({ state, index }: { state: StageState["state"]; index: number }) {
  if (state === "done") return <>✓</>;
  if (state === "failed") return <>!</>;
  if (state === "running") return <span className="spinner spinner-burgundy" />;
  return <>{index + 1}</>;
}

export default function Processing() {
  const router = useRouter();
  const pid = router.query.id as string | undefined;
  const [status, setStatus] = useState<StatusOut | null>(null);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const poll = useCallback(async () => {
    if (!pid) return;
    try {
      const s = await api.getStatus(pid);
      setStatus(s);
      if (s.status === "awaiting_review") { router.replace(`/projects/${pid}/review`); return; }
      if (s.status === "complete") { router.replace(`/projects/${pid}/output`); return; }
      if (s.status !== "failed") timer.current = setTimeout(poll, 2500);
    } catch (e: any) {
      setError(e?.message || "Could not load status");
      timer.current = setTimeout(poll, 4000);
    }
  }, [pid, router]);

  useEffect(() => {
    poll();
    return () => clearTimeout(timer.current);
  }, [poll]);

  async function retry() {
    if (!pid) return;
    setRetrying(true);
    try { await api.start(pid); setError(""); poll(); }
    catch (e: any) { setError(e?.message || "Retry failed"); }
    finally { setRetrying(false); }
  }

  const failed = status?.status === "failed";
  const rendering = status?.status === "rendering";

  return (
    <>
      <Topbar />
      <main className="page">
        <div className="container" style={{ maxWidth: 720 }}>
          <span className={`badge ${failed ? "badge-fail" : rendering ? "badge-burgundy" : "badge-info"}`}>
            <span className="dot" />
            {failed ? "Failed" : rendering ? "Rendering" : "Processing"}
          </span>
          <h1 className="page-title" style={{ marginTop: 14 }}>
            {rendering ? "Rendering your cut" : "Generating your cut"}
          </h1>
          <p className="page-sub">
            {failed
              ? "A stage failed. Completed work is preserved — you can retry from where it stopped."
              : "This runs in the background. You can leave this page and come back — we’ll keep going."}
          </p>

          <div className="card card-pad" style={{ marginTop: 26 }}>
            <div className="stepper">
              {(status?.stages ?? []).map((st, i, arr) => (
                <div key={st.name} className={`step ${st.state}`}>
                  <div className="step-rail">
                    <div className="step-dot"><StepIcon state={st.state} index={i} /></div>
                    {i < arr.length - 1 && <div className="step-line" />}
                  </div>
                  <div className="step-body">
                    <div className="step-name">{STAGE_LABEL[st.name] ?? st.name}</div>
                    <div className="step-state">
                      {st.state === "running" ? "In progress…"
                        : st.state === "done" ? "Done"
                        : st.state === "failed" ? "Failed"
                        : "Waiting"}
                    </div>
                  </div>
                </div>
              ))}
              {!status && <p className="muted">Loading…</p>}
            </div>
          </div>

          {error && <div className="banner banner-fail" style={{ marginTop: 18 }}>⚠ {error}</div>}

          {failed && (
            <div className="between" style={{ marginTop: 22 }}>
              <span className="hint">Stuck? Retrying re-runs the failed stage.</span>
              <button className="btn btn-primary" onClick={retry} disabled={retrying}>
                {retrying ? <><span className="spinner" /> Retrying…</> : "Retry"}
              </button>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
