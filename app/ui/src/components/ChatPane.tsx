import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Check, RefreshCw } from "lucide-react";
import type { HistoryEntry, WsMessage } from "../types";

// ─── Pipeline stage definitions ───────────────────────────────────────────────

const PIPELINE_STAGES = [
  { key: "entity_retrieval",    label: "Entities",  desc: "BM25 + LSH entity matching" },
  { key: "schema_linking",      label: "Schema",    desc: "3-step CHESS schema linker" },
  { key: "query_decomposition", label: "Plan",      desc: "Subproblem decomposition" },
  { key: "candidate_generation",label: "SQL×3",     desc: "Parallel candidate generation" },
  { key: "execution_scoring",   label: "Execute",   desc: "Run + score candidates" },
  { key: "correction",          label: "Correct",   desc: "Taxonomy-guided correction" },
] as const;

type StageKey = typeof PIPELINE_STAGES[number]["key"];

// ─── Pipeline progress component ──────────────────────────────────────────────

interface PipelineProgressProps {
  entry: HistoryEntry;
}

function fmtMs(v: number) {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

function PipelineProgress({ entry }: PipelineProgressProps) {
  // When done, treat all stages as completed (correction stage fires even at 0 ms)
  const completedSet = new Set(
    entry.status === "done"
      ? PIPELINE_STAGES.map((s) => s.key as StageKey)
      : entry.stages
  );
  const isStreaming = entry.status === "streaming";
  const activeIdx = isStreaming
    ? PIPELINE_STAGES.findIndex((s) => !completedSet.has(s.key as StageKey))
    : -1;

  // Use per-stage timings from WS during streaming, fallback to trace after done
  const timings: Record<string, number> =
    entry.result?.reasoning_trace?.stage_timings_ms ?? entry.stageTimings ?? {};

  return (
    <div className="mt-3 px-1 py-2">
      {/* Flat flex row: node | flex-1 line | node | flex-1 line | … — equal gaps */}
      <div className="flex items-start">
        {PIPELINE_STAGES.map((stage, idx) => {
          const done = completedSet.has(stage.key as StageKey);
          const active = idx === activeIdx;
          const timing = timings[stage.key];
          // Line leading into this node is "lit" once the previous stage is done
          const prevDone =
            idx > 0 && completedSet.has(PIPELINE_STAGES[idx - 1].key as StageKey);

          return (
            <Fragment key={stage.key}>
              {/* Connecting line — flex-1 so all nodes space evenly */}
              {idx > 0 && (
                <div
                  className="flex-1 mt-[11px] h-px transition-colors duration-700"
                  style={{ background: prevDone ? "#D97757" : "#2a2520" }}
                />
              )}

              {/* Stage node — fixed width so circles align identically */}
              <div className="flex flex-col items-center gap-1 shrink-0 w-[52px]">
                {/* Circle */}
                <div
                  className={[
                    "w-[22px] h-[22px] rounded-full flex items-center justify-center transition-all duration-400",
                    done
                      ? "bg-coral-500 shadow-[0_0_8px_rgba(217,119,87,0.45)]"
                      : active
                      ? "bg-zinc-800 ring-1 ring-coral-500 ring-offset-1 ring-offset-zinc-900 coral-pulse"
                      : "bg-zinc-800 border border-zinc-700",
                  ].join(" ")}
                >
                  {done ? (
                    <Check size={11} strokeWidth={3} className="text-zinc-950" />
                  ) : active ? (
                    <Loader2 size={11} className="text-coral-500 animate-spin" />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-zinc-700" />
                  )}
                </div>

                {/* Label */}
                <span
                  className={[
                    "text-[9px] font-semibold uppercase tracking-wide whitespace-nowrap transition-colors duration-300",
                    done ? "text-coral-500" : active ? "text-zinc-300" : "text-zinc-700",
                  ].join(" ")}
                >
                  {stage.label}
                </span>

                {/* Timing */}
                <span className="text-[9px] font-mono h-3 leading-none transition-colors">
                  {timing !== undefined ? (
                    <span className="text-zinc-600">{fmtMs(timing)}</span>
                  ) : active ? (
                    <span className="text-coral-500 animate-pulse">···</span>
                  ) : (
                    <span className="text-transparent">0ms</span>
                  )}
                </span>
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ─── Single history entry row ──────────────────────────────────────────────────

function EntryRow({ entry, isLast }: { entry: HistoryEntry; isLast: boolean }) {
  const showPipeline = entry.status === "streaming" || entry.status === "done" || entry.status === "error";

  return (
    <div className={`py-4 ${!isLast ? "border-b border-zinc-800/50" : ""}`}>
      {/* User question bubble */}
      <div className="flex items-start gap-2.5 mb-1">
        <div className="mt-0.5 w-4 h-4 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center shrink-0">
          <span className="text-[8px] font-bold text-zinc-500">Q</span>
        </div>
        <span className="text-sm text-zinc-200 leading-relaxed">{entry.question}</span>
      </div>

      {/* Pipeline visualization */}
      {showPipeline && <PipelineProgress entry={entry} />}

      {/* Result summary */}
      {entry.status === "done" && entry.result && (
        <div className="mt-2 ml-6.5 flex items-center gap-2.5 flex-wrap">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
            <span className="text-[11px] font-semibold text-emerald-500 font-mono">
              {entry.result.execution_result?.row_count ?? 0} rows
            </span>
          </div>
          <span className="text-zinc-700">·</span>
          <span className="text-[11px] font-mono text-zinc-600">
            {entry.result.latency_ms.toFixed(0)}ms
          </span>
          {entry.result.explanation && (
            <>
              <span className="text-zinc-700">·</span>
              <span className="text-[11px] text-zinc-400 truncate max-w-sm">
                {entry.result.explanation}
              </span>
            </>
          )}
        </div>
      )}

      {/* Error */}
      {entry.status === "error" && (
        <div className="mt-2 ml-6.5 flex items-center gap-1.5 text-[11px]">
          <AlertCircle size={12} className="text-red-500 shrink-0" />
          <span className="text-red-400">{entry.errorMsg ?? "Unknown error"}</span>
        </div>
      )}
    </div>
  );
}

// ─── Main ChatPane ─────────────────────────────────────────────────────────────

interface Props {
  onResult: (entry: HistoryEntry) => void;
}

const FALLBACK_SUGGESTIONS = [
  "Show the top 10 records by most recent activity",
  "How many rows are in each table?",
  "What are the most common values in the main category column?",
];

export default function ChatPane({ onResult }: Props) {
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isStreaming = history.some((e) => e.status === "streaming");

  const fetchSuggestions = useCallback(async () => {
    setSuggestionsLoading(true);
    try {
      const res = await fetch("/suggest");
      if (res.ok) {
        const data = await res.json() as { questions: string[] };
        setSuggestions(data.questions?.length ? data.questions : FALLBACK_SUGGESTIONS);
      } else {
        setSuggestions(FALLBACK_SUGGESTIONS);
      }
    } catch {
      setSuggestions(FALLBACK_SUGGESTIONS);
    } finally {
      setSuggestionsLoading(false);
    }
  }, []);

  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  const updateEntry = useCallback(
    (id: string, patch: Partial<HistoryEntry>) => {
      setHistory((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
    },
    []
  );

  const submit = useCallback(
    (question: string) => {
      if (!question.trim() || isStreaming) return;

      const id = crypto.randomUUID();
      const entry: HistoryEntry = {
        id,
        question,
        status: "pending",
        stages: [],
        stageTimings: {},
      };
      setHistory((prev) => [...prev, entry]);
      setInput("");

      wsRef.current?.close();

      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/query`
      );
      wsRef.current = ws;

      ws.onopen = () => {
        updateEntry(id, { status: "streaming" });
        ws.send(JSON.stringify({ question }));
      };

      ws.onmessage = (ev: MessageEvent<string>) => {
        const msg = JSON.parse(ev.data) as WsMessage;

        if (msg.type === "started") {
          updateEntry(id, { status: "streaming" });
        } else if (msg.type === "stage_complete") {
          setHistory((prev) =>
            prev.map((e) =>
              e.id === id
                ? {
                    ...e,
                    stages: [...e.stages, msg.stage],
                    stageTimings: { ...e.stageTimings, [msg.stage]: msg.latency_ms },
                  }
                : e
            )
          );
        } else if (msg.type === "complete") {
          const result = {
            sql: msg.sql,
            explanation: msg.explanation,
            execution_result: msg.execution_result,
            reasoning_trace: msg.reasoning_trace,
            latency_ms: msg.latency_ms,
          };
          setHistory((prev) =>
            prev.map((e) => (e.id === id ? { ...e, status: "done", result } : e))
          );
          onResult({ ...entry, status: "done", result });
        } else if (msg.type === "error") {
          updateEntry(id, { status: "error", errorMsg: msg.detail });
        }
      };

      ws.onerror = () =>
        updateEntry(id, { status: "error", errorMsg: "WebSocket connection failed" });

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
      };
    },
    [onResult, updateEntry, isStreaming]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit(input);
      }
    },
    [input, submit]
  );

  return (
    <div className="flex flex-col h-full bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center px-4 py-2.5 border-b border-zinc-800 shrink-0">
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest flex-1">
          Query
        </span>
        {isStreaming && (
          <span className="flex items-center gap-1.5 text-[11px] text-coral-500">
            <Loader2 size={11} className="animate-spin" />
            <span className="font-medium">Running pipeline</span>
          </span>
        )}
      </div>

      {/* History */}
      <div className="flex-1 overflow-y-auto px-4">
        {history.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-5 py-8">
            <div className="space-y-1 text-center">
              <p className="text-zinc-500 text-sm font-medium">Ask a question about your data</p>
              <p className="text-zinc-700 text-xs">
                Mercer will run a 6-stage agentic pipeline to generate SQL
              </p>
            </div>

            {/* Dynamic schema-aware suggestions */}
            <div className="flex flex-col gap-1.5 w-full max-w-sm">
              <div className="flex items-center justify-between mb-0.5 px-1">
                <span className="text-[10px] font-mono text-zinc-700 uppercase tracking-wider">
                  {suggestionsLoading ? "Generating suggestions…" : "Try asking"}
                </span>
                {!suggestionsLoading && (
                  <button
                    onClick={fetchSuggestions}
                    title="Refresh suggestions"
                    className="p-0.5 rounded text-zinc-700 hover:text-zinc-500 transition-colors"
                  >
                    <RefreshCw size={10} />
                  </button>
                )}
              </div>

              {suggestionsLoading ? (
                // Skeleton placeholders while LLM generates
                [0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="h-9 rounded-md bg-zinc-800/40 border border-zinc-800 animate-pulse"
                    style={{ animationDelay: `${i * 120}ms` }}
                  />
                ))
              ) : (
                suggestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => submit(q)}
                    className="text-left px-3 py-2 rounded-md bg-zinc-800/60 border border-zinc-700/50 text-xs text-zinc-400 hover:text-zinc-200 hover:border-coral-900 hover:bg-zinc-800 transition-all"
                  >
                    <span className="text-coral-600 mr-2 font-mono">›</span>
                    {q}
                  </button>
                ))
              )}
            </div>
          </div>
        ) : (
          history.map((e, i) => (
            <EntryRow key={e.id} entry={e} isLast={i === history.length - 1} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-zinc-800 shrink-0">
        <div
          className={[
            "flex items-center gap-2 px-3 py-2.5 rounded-lg bg-zinc-800 border transition-all",
            isStreaming
              ? "border-zinc-700 opacity-60"
              : "border-zinc-700 focus-within:border-coral-600 focus-within:shadow-[0_0_0_3px_rgba(217,119,87,0.08)]",
          ].join(" ")}
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={isStreaming ? "Pipeline running…" : "Ask a question about your data…"}
            className="flex-1 bg-transparent text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none disabled:cursor-not-allowed"
            autoFocus
          />
          {input.trim() && !isStreaming && (
            <button
              onClick={() => submit(input)}
              className="shrink-0 px-2 py-0.5 rounded bg-coral-600 hover:bg-coral-500 text-zinc-100 text-[11px] font-semibold transition-colors"
            >
              ↵
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
