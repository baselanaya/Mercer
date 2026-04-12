import { useCallback, useEffect, useState } from "react";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import ChatPane from "../components/ChatPane";
import SQLViewer from "../components/SQLViewer";
import ResultTable from "../components/ResultTable";
import SchemaExplorer from "../components/SchemaExplorer";
import ReasoningTrace from "../components/ReasoningTrace";
import type { HistoryEntry, SchemaResponse } from "../types";

export default function QueryPage() {
  const [schema, setSchema] = useState<SchemaResponse>({ tables: [], glossary: {} });
  const [activeEntry, setActiveEntry] = useState<HistoryEntry | null>(null);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  useEffect(() => {
    fetch("/schema")
      .then((r) => r.json())
      .then((data: SchemaResponse) => setSchema(data))
      .catch(() => {});
  }, []);

  const handleResult = useCallback((entry: HistoryEntry) => {
    setActiveEntry(entry);
  }, []);

  const recentColumns = new Set<string>(
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
    <div className="flex h-full overflow-hidden">
      {/* Left: schema sidebar */}
      <div
        className={`shrink-0 transition-all duration-200 overflow-hidden hidden sm:block border-r border-zinc-800 ${
          leftOpen ? "w-52" : "w-0"
        }`}
      >
        <SchemaExplorer
          tables={schema.tables}
          recentColumns={recentColumns}
          compact
        />
      </div>

      {/* Toggle left sidebar */}
      <button
        onClick={() => setLeftOpen((v) => !v)}
        className="hidden sm:flex items-center justify-center w-4 hover:bg-zinc-800/60 text-zinc-700 hover:text-zinc-500 transition-colors shrink-0 border-r border-zinc-800"
        title={leftOpen ? "Hide schema" : "Show schema"}
      >
        {leftOpen ? <PanelLeftClose size={12} /> : <PanelLeftOpen size={12} />}
      </button>

      {/* Center: chat + results */}
      <div className="flex-1 flex flex-col min-w-0 gap-1.5 p-1.5">
        <div className="flex-[3] min-h-0">
          <ChatPane onResult={handleResult} />
        </div>
        <div className="flex-[2] min-h-0">
          <ResultTable
            columns={execResult?.columns ?? []}
            rows={execResult?.sample_rows ?? []}
          />
        </div>
      </div>

      {/* Toggle right panel */}
      <button
        onClick={() => setRightOpen((v) => !v)}
        className="flex items-center justify-center w-4 hover:bg-zinc-800/60 text-zinc-700 hover:text-zinc-500 transition-colors shrink-0 border-l border-zinc-800"
        title={rightOpen ? "Hide SQL / trace" : "Show SQL / trace"}
      >
        {rightOpen ? <PanelRightClose size={12} /> : <PanelRightOpen size={12} />}
      </button>

      {/* Right: SQL viewer + reasoning trace */}
      <div
        className={`shrink-0 transition-all duration-200 overflow-hidden flex flex-col border-l border-zinc-800 ${
          rightOpen ? "w-[380px]" : "w-0"
        }`}
      >
        <div className="flex-1 min-h-0 p-1.5">
          <SQLViewer value={sql} />
        </div>
        <ReasoningTrace trace={trace} />
      </div>
    </div>
  );
}
