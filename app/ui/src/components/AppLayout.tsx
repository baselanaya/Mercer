import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BrainCircuit,
  GitBranch,
  MessageSquare,
  PlugZap,
  Sparkles,
  Cpu,
  AlertCircle,
} from "lucide-react";

interface HealthData {
  status: string;
  llamacpp_healthy: boolean;
  db_connected: boolean;
}

interface DBConfig {
  type: string;
  name: string;
  url: string;
}

function NavItem({
  to,
  icon: Icon,
  label,
  active,
}: {
  to: string;
  icon: React.ElementType;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      to={to}
      className={[
        "flex items-center gap-2.5 px-3 py-2 rounded-md text-xs font-medium transition-all duration-150 group",
        active
          ? "bg-zinc-800 text-zinc-200"
          : "text-zinc-600 hover:text-zinc-300 hover:bg-zinc-800/50",
      ].join(" ")}
    >
      <Icon
        size={13}
        className={active ? "text-coral-500" : "text-zinc-600 group-hover:text-zinc-400"}
      />
      {label}
    </Link>
  );
}

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthData | null>(null);
  const [dbConfig, setDbConfig] = useState<DBConfig | null>(null);
  const [tableCount, setTableCount] = useState<number>(0);

  useEffect(() => {
    const stored = localStorage.getItem("mercer_db_config");
    if (stored) {
      try {
        setDbConfig(JSON.parse(stored));
      } catch {
        // ignore
      }
    }
  }, [location]);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((d: HealthData) => setHealth(d))
      .catch(() => {});
    fetch("/schema")
      .then((r) => r.json())
      .then((d: { tables: unknown[] }) => setTableCount(d.tables?.length ?? 0))
      .catch(() => {});
  }, []);

  const dbDisplayName =
    dbConfig?.name ||
    (health?.db_connected ? "Connected" : "Not connected");

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950">
      {/* ── Sidebar ── */}
      <aside className="w-52 shrink-0 flex flex-col bg-zinc-950 border-r border-zinc-800">
        {/* Logo */}
        <div className="px-4 py-4 border-b border-zinc-800">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md bg-coral-600 flex items-center justify-center shrink-0">
              <Sparkles size={12} className="text-zinc-950" strokeWidth={2.5} />
            </div>
            <div>
              <div className="text-sm font-semibold text-zinc-200 tracking-tight leading-none">
                Mercer
              </div>
              <div className="text-[10px] font-mono text-zinc-700 mt-0.5">NL → SQL</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="px-2 py-3 space-y-0.5">
          <NavItem
            to="/query"
            icon={MessageSquare}
            label="Query"
            active={location.pathname === "/query" || location.pathname === "/"}
          />
          <NavItem
            to="/schema"
            icon={GitBranch}
            label="Schema"
            active={location.pathname === "/schema"}
          />
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Database section */}
        <div className="px-3 py-3 border-t border-zinc-800 space-y-2">
          <span className="text-[9px] font-mono text-zinc-700 uppercase tracking-widest">
            Database
          </span>

          {health === null ? (
            <div className="h-4 bg-zinc-800/60 rounded animate-pulse" />
          ) : health.db_connected ? (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                <span className="text-xs text-zinc-300 font-medium truncate">
                  {dbDisplayName}
                </span>
              </div>
              {tableCount > 0 && (
                <div className="text-[10px] font-mono text-zinc-700">
                  {tableCount} table{tableCount !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <AlertCircle size={11} className="text-red-500 shrink-0" />
              <span className="text-xs text-zinc-600">No connection</span>
            </div>
          )}

          {/* LLM status */}
          {health !== null && (
            <div className="flex items-center gap-1.5 pt-1">
              <Cpu size={11} className={health.llamacpp_healthy ? "text-emerald-600" : "text-zinc-700"} />
              <span className="text-[10px] font-mono text-zinc-700">
                {health.llamacpp_healthy ? "llama.cpp ✓" : "API mode"}
              </span>
            </div>
          )}

          <button
            onClick={() => navigate("/connect")}
            className="w-full flex items-center gap-1.5 mt-1 px-2.5 py-1.5 rounded-md border border-zinc-800 text-[11px] text-zinc-600 hover:text-zinc-400 hover:border-zinc-700 transition-colors"
          >
            <PlugZap size={11} />
            {health?.db_connected ? "Change DB" : "Connect DB"}
          </button>

          <button
            onClick={() => navigate("/model")}
            className="w-full flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-zinc-800 text-[11px] text-zinc-600 hover:text-zinc-400 hover:border-zinc-700 transition-colors"
          >
            <BrainCircuit size={11} />
            Change Model
          </button>
        </div>
      </aside>

      {/* ── Page content ── */}
      <main className="flex-1 min-w-0 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
