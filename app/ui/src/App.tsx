import { useCallback, useEffect, useState } from "react";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import ChatPane from "./components/ChatPane";
import SQLViewer from "./components/SQLViewer";
import ResultTable from "./components/ResultTable";
import SchemaExplorer from "./components/SchemaExplorer";
import ReasoningTrace from "./components/ReasoningTrace";
import type { HistoryEntry, SchemaResponse } from "./types";

export default function App() {
  const [schema, setSchema] = useState<SchemaResponse>({ tables: [], glossary: {} });
  const [activeEntry, setActiveEntry] = useState<HistoryEntry | null>(null);
  const [schemaOpen, setSchemaOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  // Fetch schema on mount
  useEffect(() => {
    fetch("/schema")
      .then((r) => r.json())
      .then((data: SchemaResponse) => setSchema(data))
      .catch(() => {/* server not up yet — silently ignore */});
  }, []);

  const handleResult = useCallback((entry: HistoryEntry) => {
    setActiveEntry(entry);
  }, []);

  // Columns used in the most recent query
  const recentColumns: Set<string> = new Set(
    activeEntry?.result
      ? (activeEntry.result.reasoning_trace?.entity_matches ?? []).map(
          (m) => `${m.table}.${m.column}`
        )
      : []
  );

  const sql = activeEntry?.result?.sql ?? "";
  const execResult = activeEntry?.result?.execution_result;
  const trace = activeEntry?.result?.reasoning_trace ?? null;

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950">
      {/* ── Schema Sidebar ── */}
      <div
        className={`shrink-0 transition-all duration-200 ${
          schemaOpen ? "w-56" : "w-0"
        } overflow-hidden hidden sm:block`}
      >
        <SchemaExplorer tables={schema.tables} recentColumns={recentColumns} />
      </div>

      {/* ── Toggle sidebar button ── */}
      <button
        onClick={() => setSchemaOpen((v) => !v)}
        className="hidden sm:flex items-center justify-center w-5 hover:bg-zinc-800 text-zinc-600 hover:text-zinc-400 transition-colors shrink-0"
        title={schemaOpen ? "Hide schema" : "Show schema"}
      >
        {schemaOpen ? <PanelLeftClose size={13} /> : <PanelLeftOpen size={13} />}
      </button>

      {/* ── Main Area ── */}
      <div className="flex-1 flex flex-col min-w-0 gap-1 p-1">
        {/* Chat (top 60%) */}
        <div className="flex-[3] min-h-0">
          <ChatPane onResult={handleResult} />
        </div>

        {/* Result table (bottom 40%) */}
        <div className="flex-[2] min-h-0">
          <ResultTable
            columns={execResult?.columns ?? []}
            rows={execResult?.sample_rows ?? []}
          />
        </div>
      </div>

      {/* ── Toggle right panel button ── */}
      <button
        onClick={() => setRightOpen((v) => !v)}
        className="flex items-center justify-center w-5 hover:bg-zinc-800 text-zinc-600 hover:text-zinc-400 transition-colors shrink-0"
        title={rightOpen ? "Hide SQL / trace" : "Show SQL / trace"}
      >
        {rightOpen ? <PanelRightClose size={13} /> : <PanelRightOpen size={13} />}
      </button>

      {/* ── Right Panel: SQL + ReasoningTrace ── */}
      <div
        className={`shrink-0 transition-all duration-200 ${
          rightOpen ? "w-96" : "w-0"
        } overflow-hidden flex flex-col border-l border-zinc-800`}
      >
        {/* SQL viewer */}
        <div className="flex-1 min-h-0 p-1">
          <SQLViewer value={sql} />
        </div>

        {/* Reasoning trace */}
        <ReasoningTrace trace={trace} />
      </div>
    </div>
  );
}
