import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReasoningTrace as Trace } from "../types";

interface Props {
  trace: Trace | null;
}

const STAGE_LABELS: Record<string, string> = {
  entity_retrieval: "Entity Retrieval",
  schema_linking: "Schema Linking",
  query_decomposition: "Query Decomposition",
  candidate_generation: "Candidate Generation",
  execution_scoring: "Execution & Scoring",
  correction: "Correction",
};

function ms(v: number) {
  return v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${v.toFixed(1)}ms`;
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[10px] font-mono">
      {children}
    </span>
  );
}

function Section({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-zinc-800 last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/50 text-left transition-colors"
      >
        {open ? (
          <ChevronDown size={12} className="text-zinc-500 shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-zinc-500 shrink-0" />
        )}
        <span className="text-xs font-medium text-zinc-300">{title}</span>
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export default function ReasoningTrace({ trace }: Props) {
  const [open, setOpen] = useState(false);

  if (!trace) return null;

  const timings = trace.stage_timings_ms ?? {};
  const totalMs = Object.values(timings).reduce((a, b) => a + b, 0);

  return (
    <div className="bg-zinc-900 border-t border-zinc-800 shrink-0">
      {/* Toggle bar */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/50 transition-colors text-left"
      >
        {open ? (
          <ChevronDown size={12} className="text-zinc-500" />
        ) : (
          <ChevronRight size={12} className="text-zinc-500" />
        )}
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          Reasoning Trace
        </span>
        {totalMs > 0 && (
          <span className="ml-auto text-[10px] font-mono text-zinc-600">
            {ms(totalMs)} total
          </span>
        )}
      </button>

      {open && (
        <div className="max-h-64 overflow-y-auto border-t border-zinc-800">
          {/* Stage timings */}
          {Object.keys(timings).length > 0 && (
            <Section title="Stage Timings" defaultOpen>
              <div className="space-y-1">
                {Object.entries(timings).map(([stage, t]) => (
                  <div key={stage} className="flex items-center gap-2">
                    <span className="text-xs text-zinc-500 w-44 truncate">
                      {STAGE_LABELS[stage] ?? stage}
                    </span>
                    <div className="flex-1 h-1 rounded bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full rounded bg-blue-600"
                        style={{ width: `${Math.min(100, (t / totalMs) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-zinc-400 w-16 text-right">
                      {ms(t)}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Entity matches */}
          {trace.entity_matches && trace.entity_matches.length > 0 && (
            <Section title={`Entity Matches (${trace.entity_matches.length})`}>
              <div className="space-y-1">
                {trace.entity_matches.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <Badge>{m.token}</Badge>
                    <span className="text-zinc-500">→</span>
                    <span className="font-mono text-zinc-300">
                      {m.table}.{m.column}
                    </span>
                    <span className="ml-auto text-[10px] font-mono text-zinc-600">
                      {m.score.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Tables selected */}
          {trace.tables_selected && trace.tables_selected.length > 0 && (
            <Section title={`Schema Linking (${trace.tables_selected.length} tables)`}>
              <div className="flex flex-wrap gap-1.5">
                {trace.tables_selected.map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
              </div>
            </Section>
          )}

          {/* Candidates */}
          {trace.candidates && trace.candidates.length > 0 && (
            <Section title={`Candidates (${trace.candidates.length})`}>
              <div className="space-y-1">
                {trace.candidates.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="text-zinc-500 w-4">{i + 1}.</span>
                    <Badge>{c.strategy}</Badge>
                    <div className="flex-1 h-1 rounded bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full rounded bg-blue-600"
                        style={{ width: `${c.score * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-zinc-400 w-12 text-right">
                      {c.score.toFixed(4)}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Correction steps */}
          {trace.correction_steps !== undefined && trace.correction_steps > 0 && (
            <Section title={`Correction Steps (${trace.correction_steps})`}>
              <p className="text-xs text-zinc-500">
                Query was revised {trace.correction_steps} time
                {trace.correction_steps !== 1 ? "s" : ""} by the correction stage.
              </p>
            </Section>
          )}

          {/* Glossary expansions */}
          {trace.glossary_expansions &&
            Object.keys(trace.glossary_expansions).length > 0 && (
              <Section title="Glossary Expansions">
                <div className="space-y-1">
                  {Object.entries(trace.glossary_expansions).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2 text-xs">
                      <Badge>{k}</Badge>
                      <span className="text-zinc-500">→</span>
                      <span className="text-zinc-300">{v}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}
        </div>
      )}
    </div>
  );
}
