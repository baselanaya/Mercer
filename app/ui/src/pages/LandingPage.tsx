import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Cpu,
  Database,
  Sparkles,
  Zap,
} from "lucide-react";

interface SetupStatus {
  modelConfigured: boolean;
  dbConfigured: boolean;
  backendName: string;
  dbName: string;
  llamacppHealthy: boolean;
}

function useSetupStatus(): SetupStatus {
  const modelRaw = localStorage.getItem("mercer_model_config");
  const dbRaw = localStorage.getItem("mercer_db_config");
  const model = modelRaw ? JSON.parse(modelRaw) : null;
  const db = dbRaw ? JSON.parse(dbRaw) : null;

  const backendLabels: Record<string, string> = {
    ollama: "Ollama",
    llamacpp: "llama.cpp",
    anthropic: "Anthropic Claude",
    openai: "OpenAI",
  };

  return {
    modelConfigured: Boolean(model),
    dbConfigured: Boolean(db),
    backendName: model ? (backendLabels[model.backend] ?? model.backend) : "Not configured",
    dbName: db?.name ?? "Not connected",
    llamacppHealthy: false,
  };
}

// ─── Step indicator ────────────────────────────────────────────────────────

function Step({
  n,
  label,
  done,
  active,
}: {
  n: number;
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={[
          "w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 transition-colors",
          done
            ? "bg-emerald-500 text-zinc-950"
            : active
            ? "bg-coral-600 text-zinc-950"
            : "bg-zinc-800 text-zinc-600",
        ].join(" ")}
      >
        {done ? <CheckCircle2 size={13} /> : n}
      </div>
      <span
        className={[
          "text-xs font-medium transition-colors",
          done ? "text-zinc-400" : active ? "text-zinc-200" : "text-zinc-600",
        ].join(" ")}
      >
        {label}
      </span>
    </div>
  );
}

function StepConnector({ done }: { done: boolean }) {
  return (
    <div className={["h-px w-8 shrink-0", done ? "bg-emerald-700" : "bg-zinc-800"].join(" ")} />
  );
}

// ─── Feature pill ──────────────────────────────────────────────────────────

function Feature({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-900/60 border border-zinc-800 text-xs text-zinc-500">
      <Icon size={11} className="text-zinc-600" />
      {label}
    </div>
  );
}

// ─── DB logo miniatures ────────────────────────────────────────────────────

function DBLogos() {
  return (
    <div className="flex items-center gap-2">
      {/* PostgreSQL */}
      <div className="w-7 h-7 rounded-lg overflow-hidden" title="PostgreSQL">
        <svg viewBox="0 0 28 28" className="w-full h-full">
          <rect width="28" height="28" rx="6" fill="#1a2f4a" />
          <text x="14" y="20" textAnchor="middle" fontSize="14" fill="#4a8cbf">🐘</text>
        </svg>
      </div>
      {/* MySQL */}
      <div className="w-7 h-7 rounded-lg overflow-hidden" title="MySQL">
        <svg viewBox="0 0 28 28" className="w-full h-full">
          <rect width="28" height="28" rx="6" fill="#1c2312" />
          <text x="14" y="20" textAnchor="middle" fontSize="14">🐬</text>
        </svg>
      </div>
      {/* SQLite */}
      <div className="w-7 h-7 rounded-lg overflow-hidden" title="SQLite">
        <svg viewBox="0 0 28 28" className="w-full h-full">
          <rect width="28" height="28" rx="6" fill="#002244" />
          <text x="14" y="20" textAnchor="middle" fontSize="11" fill="#4a9fd4" fontFamily="monospace" fontWeight="bold">db</text>
        </svg>
      </div>
      {/* DuckDB */}
      <div className="w-7 h-7 rounded-lg overflow-hidden" title="DuckDB">
        <svg viewBox="0 0 28 28" className="w-full h-full">
          <rect width="28" height="28" rx="6" fill="#201800" />
          <text x="14" y="20" textAnchor="middle" fontSize="14">🦆</text>
        </svg>
      </div>
    </div>
  );
}

// ─── Main landing page ─────────────────────────────────────────────────────

export default function LandingPage() {
  const navigate = useNavigate();
  const status = useSetupStatus();
  const [serverOk, setServerOk] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((d) => setServerOk(d.status === "ok"))
      .catch(() => setServerOk(false));
  }, []);

  const fullyConfigured = status.modelConfigured && status.dbConfigured;
  const nextStep = !status.modelConfigured
    ? "/model"
    : !status.dbConfigured
    ? "/connect"
    : "/query";
  const ctaLabel = fullyConfigured
    ? "Open Query Console"
    : !status.modelConfigured
    ? "Configure Model"
    : "Connect Database";

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col">
      {/* Top bar */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-zinc-900">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-coral-600 flex items-center justify-center shadow-[0_0_16px_rgba(217,119,87,0.4)]">
            <Sparkles size={13} className="text-zinc-950" strokeWidth={2.5} />
          </div>
          <span className="text-sm font-semibold text-zinc-200 tracking-tight">Mercer</span>
        </div>

        {/* Setup steps */}
        <div className="flex items-center gap-2">
          <Step n={1} label="Model" done={status.modelConfigured} active={!status.modelConfigured} />
          <StepConnector done={status.modelConfigured} />
          <Step
            n={2}
            label="Database"
            done={status.dbConfigured}
            active={status.modelConfigured && !status.dbConfigured}
          />
          <StepConnector done={status.dbConfigured} />
          <Step n={3} label="Query" done={false} active={fullyConfigured} />
        </div>

        {/* Server status dot */}
        <div className="flex items-center gap-1.5">
          <span
            className={[
              "w-1.5 h-1.5 rounded-full",
              serverOk === null
                ? "bg-zinc-700 animate-pulse"
                : serverOk
                ? "bg-emerald-500"
                : "bg-red-500",
            ].join(" ")}
          />
          <span className="text-[11px] font-mono text-zinc-600">
            {serverOk === null ? "checking…" : serverOk ? "server ok" : "server offline"}
          </span>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-16 text-center">
        {/* Glow backdrop */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-[600px] h-[300px] bg-coral-600/5 rounded-full blur-3xl" />
        </div>

        <div className="relative z-10 flex flex-col items-center gap-8 max-w-2xl">
          {/* Icon */}
          <div className="w-16 h-16 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center shadow-[0_0_40px_rgba(217,119,87,0.15),inset_0_1px_0_rgba(255,255,255,0.04)]">
            <div className="w-10 h-10 rounded-xl bg-coral-600 flex items-center justify-center shadow-[0_0_24px_rgba(217,119,87,0.5)]">
              <Sparkles size={18} className="text-zinc-950" strokeWidth={2.5} />
            </div>
          </div>

          {/* Heading */}
          <div className="space-y-3">
            <h1 className="text-5xl font-semibold text-zinc-100 tracking-tight leading-none">
              Mercer
            </h1>
            <p className="text-lg text-zinc-500 font-light">
              Natural language to SQL — for messy real-world schemas
            </p>
          </div>

          {/* Feature pills */}
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Feature icon={Zap} label="6-stage agentic pipeline" />
            <Feature icon={Cpu} label="Local or cloud inference" />
            <Feature icon={Database} label="Multi-database support" />
            <Feature icon={Sparkles} label="Schema-aware reasoning" />
          </div>

          {/* DB logos */}
          <div className="flex flex-col items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest">
              Supported databases
            </span>
            <DBLogos />
          </div>

          {/* Status cards — shown when partially configured */}
          {(status.modelConfigured || status.dbConfigured) && (
            <div className="flex gap-3 w-full">
              <div
                className={[
                  "flex-1 flex items-center gap-2.5 px-4 py-3 rounded-xl border text-left",
                  status.modelConfigured
                    ? "border-emerald-900/60 bg-emerald-950/20"
                    : "border-zinc-800 bg-zinc-900/40",
                ].join(" ")}
              >
                {status.modelConfigured ? (
                  <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />
                ) : (
                  <Circle size={14} className="text-zinc-700 shrink-0" />
                )}
                <div>
                  <div className="text-[11px] font-mono text-zinc-600 uppercase tracking-widest">
                    Model
                  </div>
                  <div className="text-xs text-zinc-300 font-medium mt-0.5">
                    {status.backendName}
                  </div>
                </div>
              </div>

              <div
                className={[
                  "flex-1 flex items-center gap-2.5 px-4 py-3 rounded-xl border text-left",
                  status.dbConfigured
                    ? "border-emerald-900/60 bg-emerald-950/20"
                    : "border-zinc-800 bg-zinc-900/40",
                ].join(" ")}
              >
                {status.dbConfigured ? (
                  <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />
                ) : (
                  <Circle size={14} className="text-zinc-700 shrink-0" />
                )}
                <div>
                  <div className="text-[11px] font-mono text-zinc-600 uppercase tracking-widest">
                    Database
                  </div>
                  <div className="text-xs text-zinc-300 font-medium mt-0.5">
                    {status.dbName}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* CTA */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(nextStep)}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-coral-600 hover:bg-coral-500 text-zinc-950 text-sm font-semibold transition-all shadow-[0_0_24px_rgba(217,119,87,0.35)] hover:shadow-[0_0_32px_rgba(217,119,87,0.5)]"
            >
              {ctaLabel}
              <ArrowRight size={15} />
            </button>
            {!fullyConfigured && (
              <button
                onClick={() => navigate("/query")}
                className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
              >
                Skip setup →
              </button>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-8 py-4 border-t border-zinc-900 flex items-center justify-between">
        <span className="text-[11px] font-mono text-zinc-800">
          Mercer · Text-to-SQL · Phase 4
        </span>
        <span className="text-[11px] font-mono text-zinc-800">
          BM25 + LSH + Multi-candidate SQL generation
        </span>
      </footer>
    </div>
  );
}
