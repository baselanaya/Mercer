import { useState } from "react";
import { ChevronDown, ChevronRight, Clock } from "lucide-react";
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
  return v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${v.toFixed(0)}ms`;
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="px-1.5 py-0.5 rounded-sm bg-zinc-800 border border-zinc-700 text-zinc-400 text-[10px] font-mono">
      {children}
    </span>
  );
}

function Section({
  title,
  children,
  defaultOpen = false,
  badge,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-zinc-800 last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/40 text-left transition-colors"
      >
        {open
          ? <ChevronDown size={11} className="text-zinc-600 shrink-0" />
          : <ChevronRight size={11} className="text-zinc-600 shrink-0" />
        }
        <span className="text-[11px] font-medium text-zinc-400 flex-1">{title}</span>
        {badge}
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
  const maxMs = Math.max(...Object.values(timings), 1);

  return (
    <div className="bg-zinc-900 border-t border-zinc-800 shrink-0">
      {/* Toggle bar */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-zinc-800/40 transition-colors text-left"
      >
        {open
          ? <ChevronDown size={11} className="text-zinc-600" />
          : <ChevronRight size={11} className="text-zinc-600" />
        }
        <Clock size={11} className="text-zinc-600 shrink-0" />
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest flex-1">
          Pipeline Details
        </span>
        {totalMs > 0 && (
          <span className="text-[10px] font-mono text-zinc-600 shrink-0">
            {ms(totalMs)} total
          </span>
        )}
      </button>

      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-zinc-800">

          {/* Stage timings */}
          {Object.keys(timings).length > 0 && (
            <Section
              title="Stage Timings"
              defaultOpen
              badge={
                <span className="text-[10px] font-mono text-zinc-600">{ms(totalMs)}</span>
              }
            >
              <div className="space-y-2.5">
                {Object.entries(timings).map(([stage, t]) => {
                  const pct = Math.min(100, (t / maxMs) * 100);
                  return (
                    <div key={stage}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-zinc-500">
                          {STAGE_LABELS[stage] ?? stage}
                        </span>
                        <span className="text-[10px] font-mono text-zinc-500">{ms(t)}</span>
                      </div>
                      <div className="h-1 rounded-full bg-zinc-800 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-coral-600 transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Entity matches */}
          {trace.entity_matches && trace.entity_matches.length > 0 && (
            <Section
              title="Entity Matches"
              badge={<Tag>{trace.entity_matches.length}</Tag>}
            >
              <div className="space-y-1.5">
                {trace.entity_matches.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <Tag>{m.token}</Tag>
                    <span className="text-zinc-700">→</span>
                    <span className="font-mono text-zinc-300 text-[11px]">
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
            <Section
              title="Schema Linking"
              badge={<Tag>{trace.tables_selected.length} tables</Tag>}
            >
              <div className="flex flex-wrap gap-1.5">
                {trace.tables_selected.map((t) => (
                  <span
                    key={t}
                    className="px-2 py-0.5 rounded-sm bg-zinc-800 border border-zinc-700 text-zinc-300 text-[11px] font-mono"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {/* Candidates */}
          {trace.candidates && trace.candidates.length > 0 && (
            <Section
              title="SQL Candidates"
              badge={<Tag>{trace.candidates.length}</Tag>}
            >
              <div className="space-y-2">
                {trace.candidates.map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-zinc-600 w-3">{i + 1}</span>
                    <span className="px-1.5 py-0.5 rounded-sm bg-zinc-800 border border-zinc-700 text-[10px] font-mono text-zinc-400">
                      {c.strategy}
                    </span>
                    <div className="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-coral-600"
                        style={{ width: `${c.score * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-zinc-500 w-12 text-right">
                      {c.score.toFixed(4)}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Correction steps */}
          {!!trace.correction_steps && (
            <Section
              title="Corrections Applied"
              badge={<Tag>{trace.correction_steps}×</Tag>}
            >
              <p className="text-[11px] text-zinc-500">
                The correction stage revised the query {trace.correction_steps} time
                {trace.correction_steps !== 1 ? "s" : ""} before finalizing.
              </p>
            </Section>
          )}

          {/* Glossary expansions */}
          {trace.glossary_expansions &&
            Object.keys(trace.glossary_expansions).length > 0 && (
              <Section
                title="Glossary Expansions"
                badge={<Tag>{Object.keys(trace.glossary_expansions).length}</Tag>}
              >
                <div className="space-y-1.5">
                  {Object.entries(trace.glossary_expansions).map(([k, v]) => (
                    <div key={k} className="flex items-start gap-2 text-xs">
                      <Tag>{k}</Tag>
                      <span className="text-zinc-700 mt-0.5">→</span>
                      <span className="text-zinc-400 text-[11px] leading-relaxed">{v}</span>
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
