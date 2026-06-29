import { useRouter } from "next/router";

export default function Topbar({ wide = false }: { wide?: boolean }) {
  const router = useRouter();
  return (
    <header className="topbar">
      <div className={wide ? "container-wide topbar-inner" : "container topbar-inner"}>
        <span
          className="brand"
          style={{ cursor: "pointer" }}
          onClick={() => router.push("/")}
        >
          iSOFT
        </span>
        <span className="brand-divider" />
        <span className="brand-title">Video Summarisation</span>
        <span className="topbar-spacer" />
        <button className="btn btn-ghost btn-sm" onClick={() => router.push("/")}>
          + New summary
        </button>
      </div>
    </header>
  );
}
