import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { HistoryEntry, WsMessage } from "../types";

const STAGE_LABELS: Record<string, string> = {
  entity_retrieval: "Retrieving entities",
  schema_linking: "Linking schema",
  query_decomposition: "Decomposing query",
  candidate_generation: "Generating candidates",
  execution_scoring: "Scoring execution",
  correction: "Applying corrections",
};

interface Props {
  onResult: (entry: HistoryEntry) => void;
}

function EntryRow({ entry }: { entry: HistoryEntry }) {
  return (
    <div className="py-3 border-b border-zinc-800/60 last:border-0">
      {/* Question */}
      <div className="flex items-start gap-2 mb-1.5">
        <span className="mt-0.5 text-zinc-600 text-xs font-mono shrink-0">›</span>
        <span className="text-sm text-zinc-200 leading-snug">{entry.question}</span>
      </div>

      {/* Status */}
      <div className="ml-4">
        {entry.status === "pending" && (
          <div className="flex items-center gap-1.5 text-xs text-zinc-500">
            <Loader2 size={11} className="animate-spin" />
            Connecting…
          </div>
        )}

        {entry.status === "streaming" && (
          <div className="space-y-0.5">
            {entry.stages.map((s, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs text-zinc-500">
                {i === entry.stages.length - 1 ? (
                  <Loader2 size={11} className="animate-spin text-blue-400 shrink-0" />
                ) : (
                  <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
                )}
                {STAGE_LABELS[s] ?? s}
              </div>
            ))}
          </div>
        )}

        {entry.status === "done" && entry.result && (
          <div className="flex items-center gap-2 text-xs">
            <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
            <span className="text-emerald-400 font-mono">
              {entry.result.execution_result?.row_count ?? 0} rows
            </span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500 font-mono">
              {entry.result.latency_ms.toFixed(0)}ms
            </span>
            {entry.result.explanation && (
              <>
                <span className="text-zinc-600">·</span>
                <span className="text-zinc-400 truncate max-w-xs">
                  {entry.result.explanation}
                </span>
              </>
            )}
          </div>
        )}

        {entry.status === "error" && (
          <div className="flex items-center gap-1.5 text-xs text-red-400">
            <AlertCircle size={11} className="shrink-0" />
            {entry.errorMsg ?? "Unknown error"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPane({ onResult }: Props) {
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [input, setInput] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  const updateEntry = useCallback(
    (id: string, patch: Partial<HistoryEntry>) => {
      setHistory((prev) =>
        prev.map((e) => (e.id === id ? { ...e, ...patch } : e))
      );
    },
    []
  );

  const submit = useCallback(
    (question: string) => {
      if (!question.trim()) return;

      const id = crypto.randomUUID();
      const entry: HistoryEntry = {
        id,
        question,
        status: "pending",
        stages: [],
      };
      setHistory((prev) => [...prev, entry]);
      setInput("");

      // Close any existing connection
      wsRef.current?.close();

      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/query`);
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
                ? { ...e, stages: [...e.stages, msg.stage] }
                : e
            )
          );
        } else if (msg.type === "complete") {
          // Fetch full result (explanation + reasoning trace) from REST
          fetch("/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
          })
            .then((r) => r.json())
            .then((result) => {
              setHistory((prev) =>
                prev.map((e) => (e.id === id ? { ...e, status: "done", result } : e))
              );
              onResult({ ...entry, status: "done", result });
            })
            .catch(() => {
              // Fall back to WS data if REST fails
              updateEntry(id, { status: "done" });
            });
        } else if (msg.type === "error") {
          updateEntry(id, { status: "error", errorMsg: msg.detail });
        }
      };

      ws.onerror = () => {
        updateEntry(id, {
          status: "error",
          errorMsg: "WebSocket connection failed",
        });
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
      };
    },
    [onResult, updateEntry]
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
      <div className="flex items-center px-3 py-2 border-b border-zinc-800 shrink-0">
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          Query
        </span>
        {history.some((e) => e.status === "streaming") && (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-blue-400">
            <Loader2 size={11} className="animate-spin" />
            Running
          </span>
        )}
      </div>

      {/* History list */}
      <div className="flex-1 overflow-y-auto px-3">
        {history.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
            <span className="text-zinc-600 text-sm">Ask a question about your data</span>
            <span className="text-zinc-700 text-xs font-mono">
              e.g. "How many orders were placed last month?"
            </span>
          </div>
        ) : (
          history.map((e) => <EntryRow key={e.id} entry={e} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-3 py-2.5 border-t border-zinc-800 shrink-0">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-700 focus-within:border-blue-600 transition-colors">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question… (Enter to submit)"
            className="flex-1 bg-transparent text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none"
            autoFocus
          />
          {input.trim() && (
            <kbd className="text-[10px] text-zinc-600 font-mono shrink-0">↵</kbd>
          )}
        </div>
      </div>
    </div>
  );
}
