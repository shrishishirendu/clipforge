import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";

import Topbar from "@/components/Topbar";
import { ApiError, ClipListOut, SegmentEdit, SegmentOut, api, fmtTime } from "@/lib/api";

const NUDGE = 0.5; // seconds (snapped to silence server-side, FR-15)

export default function Review() {
  const router = useRouter();
  const pid = router.query.id as string | undefined;
  const [clip, setClip] = useState<ClipListOut | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<"" | "approving" | "reediting">("");
  const [showGaps, setShowGaps] = useState(false);
  const pendingRemove = useRef<{ seg: SegmentOut; timer: ReturnType<typeof setTimeout> } | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const dragIndex = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!pid) return;
    try {
      const cl = await api.getClipList(pid);
      if (cl.approval_status === "approved") { router.replace(`/projects/${pid}/processing`); return; }
      setClip(cl);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 404) { router.replace(`/projects/${pid}/processing`); return; }
      setError(e?.message || "Could not load the clip list");
    }
  }, [pid, router]);

  useEffect(() => { load(); }, [load]);

  function flash(msg: string) { setToast(msg); setTimeout(() => setToast(""), 2600); }

  async function save(edits: SegmentEdit[]) {
    if (!pid) return;
    setSaving(true);
    try {
      setClip(await api.patchClipList(pid, edits));
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 422) flash("That nudge would collapse the clip.");
      else setError(e?.message || "Edit failed");
      await load(); // resync
    } finally {
      setSaving(false);
    }
  }

  // --- deferred remove with undo (no false destructive call) ---
  function commitRemoveNow() {
    const p = pendingRemove.current;
    if (!p) return Promise.resolve();
    clearTimeout(p.timer);
    pendingRemove.current = null;
    setPendingId(null);
    return save([{ segment_id: p.seg.id, remove: true }]);
  }
  async function flushPending() { if (pendingRemove.current) await commitRemoveNow(); }

  async function removeSeg(seg: SegmentOut) {
    await flushPending();
    setClip((c) => c && { ...c, segments: c.segments.filter((s) => s.id !== seg.id) });
    setPendingId(seg.id);
    const timer = setTimeout(() => { commitRemoveNow(); }, 5000);
    pendingRemove.current = { seg, timer };
  }
  function undoRemove() {
    const p = pendingRemove.current;
    if (!p) return;
    clearTimeout(p.timer);
    pendingRemove.current = null;
    setPendingId(null);
    setClip((c) => c && { ...c, segments: [...c.segments, p.seg].sort((a, b) => a.order - b.order) });
  }

  async function reorder(from: number, to: number) {
    if (!clip || from === to || to < 0 || to >= clip.segments.length) return;
    await flushPending();
    const segs = [...clip.segments];
    const [m] = segs.splice(from, 1);
    segs.splice(to, 0, m);
    setClip({ ...clip, segments: segs }); // optimistic
    save(segs.map((s, i) => ({ segment_id: s.id, order: i })));
  }

  async function nudge(seg: SegmentOut, edge: "start" | "end", delta: number) {
    await flushPending();
    save([{ segment_id: seg.id, [edge === "start" ? "start_sec" : "end_sec"]:
            Math.max(0, (edge === "start" ? seg.start_sec : seg.end_sec) + delta) }]);
  }
  async function toggleLock(seg: SegmentOut) { await flushPending(); save([{ segment_id: seg.id, locked: !seg.locked }]); }

  async function onApprove() {
    await flushPending();
    const gaps = gapList();
    if (gaps.length > 0) { setShowGaps(true); return; }
    doApprove(false);
  }
  async function doApprove(confirm: boolean) {
    if (!pid) return;
    setBusy("approving"); setShowGaps(false);
    try { await api.approve(pid, confirm); router.push(`/projects/${pid}/processing`); }
    catch (e: any) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.error === "uncovered_key_points") setShowGaps(true);
      else setError(e?.message || "Approve failed");
      setBusy("");
    }
  }
  async function onReedit() {
    if (!pid) return;
    await flushPending();
    setBusy("reediting");
    try { await api.reedit(pid); router.push(`/projects/${pid}/processing`); }
    catch (e: any) { setError(e?.message || "Re-edit failed"); setBusy(""); }
  }

  function coveredIds() { return new Set((clip?.segments ?? []).map((s) => s.key_point_id).filter(Boolean)); }
  function gapList() { const c = coveredIds(); return (clip?.key_points ?? []).filter((kp) => !c.has(kp.id)); }

  if (error && !clip) return (
    <><Topbar /><main className="page"><div className="container"><div className="banner banner-fail">⚠ {error}</div></div></main></>
  );
  if (!clip) return (<><Topbar /><main className="page"><div className="center-screen"><span className="spinner spinner-burgundy" /></div></main></>);

  const kpById = Object.fromEntries(clip.key_points.map((k) => [k.id, k]));
  const totalSec = clip.segments.reduce((a, s) => a + (s.end_sec - s.start_sec), 0);
  const gaps = gapList();
  const covered = clip.key_points.length - gaps.length;
  const within = totalSec >= clip.target_min_sec && totalSec <= clip.target_max_sec;
  const over = totalSec > clip.target_max_sec;
  const canApprove = clip.segments.length > 0 && busy === "";

  return (
    <>
      <Topbar wide />
      <main className="page">
        <div className="container-wide">
          <div className="between" style={{ marginBottom: 8 }}>
            <span className="badge badge-warn"><span className="dot" /> Needs your review</span>
            {saving && <span className="hint"><span className="spinner spinner-burgundy" /> saving…</span>}
          </div>
          <h1 className="page-title">Review the proposed cut</h1>
          <p className="page-sub">
            This is the AI’s proposed 3–4 minute cut. Reorder, trim, lock or remove clips,
            then approve. Nothing renders until you approve.
          </p>

          <div className="grid-2" style={{ marginTop: 24 }}>
            {/* segments */}
            <div className="stack">
              {clip.segments.length === 0 && (
                <div className="banner banner-warn">No clips left — undo a removal or re-edit the cut.</div>
              )}
              {clip.segments.map((seg, i) => {
                const kp = seg.key_point_id ? kpById[seg.key_point_id] : null;
                return (
                  <div
                    key={seg.id}
                    className={`seg${seg.locked ? " locked" : ""}`}
                    draggable={!seg.locked && busy === ""}
                    onDragStart={() => (dragIndex.current = i)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => { if (dragIndex.current !== null) reorder(dragIndex.current, i); dragIndex.current = null; }}
                  >
                    <div className="seg-order">{i + 1}</div>
                    <div className="seg-main">
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <span className="seg-time">{fmtTime(seg.start_sec)} – {fmtTime(seg.end_sec)} · {(seg.end_sec - seg.start_sec).toFixed(1)}s</span>
                        <span className="row" style={{ gap: 8 }}>
                          {kp && <span className="kp-chip" title={kp.source}>{kp.text.slice(0, 40)}{kp.text.length > 40 ? "…" : ""}</span>}
                          <span className="badge" title="model confidence">{Math.round(seg.confidence * 100)}%</span>
                        </span>
                      </div>
                      <div className="seg-snippet">{seg.transcript_snippet || <span className="muted">(no transcript)</span>}</div>
                      <div className="seg-controls" style={{ marginTop: 12 }}>
                        <button className="icon-btn" title="Move up" disabled={i === 0 || busy !== ""} onClick={() => reorder(i, i - 1)}>↑</button>
                        <button className="icon-btn" title="Move down" disabled={i === clip.segments.length - 1 || busy !== ""} onClick={() => reorder(i, i + 1)}>↓</button>
                        <span style={{ width: 8 }} />
                        <span className="hint" style={{ marginRight: 2 }}>start</span>
                        <button className="icon-btn" title="Nudge start earlier" onClick={() => nudge(seg, "start", -NUDGE)}>−</button>
                        <button className="icon-btn" title="Nudge start later" onClick={() => nudge(seg, "start", +NUDGE)}>+</button>
                        <span className="hint" style={{ margin: "0 2px 0 6px" }}>end</span>
                        <button className="icon-btn" title="Nudge end earlier" onClick={() => nudge(seg, "end", -NUDGE)}>−</button>
                        <button className="icon-btn" title="Nudge end later" onClick={() => nudge(seg, "end", +NUDGE)}>+</button>
                        <span style={{ flex: 1 }} />
                        <button className={`icon-btn${seg.locked ? " active" : ""}`} title={seg.locked ? "Locked — survives re-edit" : "Lock"} onClick={() => toggleLock(seg)}>{seg.locked ? "🔒" : "🔓"}</button>
                        <button className="icon-btn" title="Remove" onClick={() => removeSeg(seg)}>✕</button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* coverage + actions */}
            <div className="stack" style={{ position: "sticky", top: 80 }}>
              <div className="card card-pad">
                <div className="between">
                  <h3>Total length</h3>
                  <span className={`badge ${within ? "badge-ok" : over ? "badge-warn" : "badge-info"}`}>
                    {within ? "On target" : over ? "Over target" : "Under target"}
                  </span>
                </div>
                <div style={{ fontSize: 30, fontWeight: 800, marginTop: 6 }} className="tnum">{fmtTime(totalSec)}</div>
                <div className="hint">target {fmtTime(clip.target_min_sec)}–{fmtTime(clip.target_max_sec)} · {clip.segments.length} clips</div>
              </div>

              <div className="card card-pad">
                <div className="between">
                  <h3>Key-point coverage</h3>
                  <span className={`badge ${gaps.length ? "badge-warn" : "badge-ok"}`}>{covered}/{clip.key_points.length}</span>
                </div>
                <div className="stack" style={{ gap: 8, marginTop: 12, maxHeight: 280, overflow: "auto" }}>
                  {clip.key_points.map((kp) => {
                    const ok = coveredIds().has(kp.id);
                    return (
                      <div key={kp.id} className="row" style={{ alignItems: "flex-start", gap: 8 }}>
                        <span style={{ color: ok ? "var(--ok)" : "var(--warn)", fontWeight: 700 }}>{ok ? "✓" : "○"}</span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13.5 }}>{kp.text.slice(0, 90)}{kp.text.length > 90 ? "…" : ""}</div>
                          <div className="hint" style={{ fontSize: 12 }}>{kp.source}</div>
                        </div>
                      </div>
                    );
                  })}
                  {clip.key_points.length === 0 && <span className="hint">No key points extracted.</span>}
                </div>
              </div>

              <button className="btn btn-primary btn-lg" disabled={!canApprove} onClick={onApprove}>
                {busy === "approving" ? <><span className="spinner" /> Approving…</> : "Approve & render →"}
              </button>
              <button className="btn btn-ghost" disabled={busy !== ""} onClick={onReedit}>
                {busy === "reediting" ? <><span className="spinner spinner-burgundy" /> Re-editing…</> : "↻ Re-edit cut (keeps locked clips)"}
              </button>
              {gaps.length > 0 && <p className="hint" style={{ textAlign: "center" }}>{gaps.length} key point{gaps.length > 1 ? "s" : ""} not covered — you’ll be asked to confirm.</p>}
            </div>
          </div>
        </div>
      </main>

      {error && clip && <div className="toast">⚠ {error}<button onClick={() => setError("")}>Dismiss</button></div>}
      {pendingId && <div className="toast">Clip removed<button onClick={undoRemove}>Undo</button></div>}
      {toast && <div className="toast">{toast}</div>}

      {showGaps && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(20,14,18,.45)", display: "grid", placeItems: "center", zIndex: 60 }}
             onClick={() => setShowGaps(false)}>
          <div className="card card-pad" style={{ maxWidth: 460, margin: 20 }} onClick={(e) => e.stopPropagation()}>
            <h3>Approve with gaps?</h3>
            <p className="page-sub" style={{ marginTop: 8 }}>
              {gaps.length} key point{gaps.length > 1 ? "s aren’t" : " isn’t"} covered by the current cut.
              You can approve anyway, or re-edit to cover them.
            </p>
            <ul className="stack" style={{ gap: 6, margin: "14px 0", paddingLeft: 18 }}>
              {gaps.slice(0, 5).map((kp) => <li key={kp.id} style={{ fontSize: 13.5 }}>{kp.text.slice(0, 80)}</li>)}
            </ul>
            <div className="between">
              <button className="btn btn-ghost" onClick={() => setShowGaps(false)}>Keep editing</button>
              <button className="btn btn-primary" onClick={() => doApprove(true)}>Approve anyway →</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
