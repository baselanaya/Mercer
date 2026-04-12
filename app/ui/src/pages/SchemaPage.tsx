import { useEffect, useState } from "react";
import SchemaExplorer, { type SchemaViewMode } from "../components/SchemaExplorer";
import type { SchemaResponse } from "../types";

export default function SchemaPage() {
  const [schema, setSchema] = useState<SchemaResponse>({ tables: [], glossary: {} });
  const [viewMode, setViewMode] = useState<SchemaViewMode>("graph");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/schema")
      .then((r) => r.json())
      .then((data: SchemaResponse) => {
        setSchema(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-zinc-600 text-sm">
          <div className="w-1.5 h-1.5 rounded-full bg-coral-500 animate-pulse" />
          Loading schema…
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-zinc-200">Schema Explorer</span>
          {schema.tables.length > 0 && (
            <span className="text-[10px] font-mono text-zinc-600">
              {schema.tables.length} tables ·{" "}
              {schema.tables.reduce((n, t) => n + t.columns.length, 0)} columns
            </span>
          )}
        </div>

        {/* View toggle */}
        <div className="flex items-center gap-0.5 bg-zinc-800/60 p-0.5 rounded-md">
          {(["graph", "tree"] as SchemaViewMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={[
                "px-3 py-1 rounded text-[11px] font-medium capitalize transition-all",
                viewMode === mode
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-600 hover:text-zinc-400",
              ].join(" ")}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Glossary ribbon (if any) */}
      {Object.keys(schema.glossary).length > 0 && (
        <div className="flex items-center gap-3 px-5 py-2 border-b border-zinc-800 bg-zinc-900/40 overflow-x-auto shrink-0">
          <span className="text-[9px] font-mono text-zinc-700 uppercase tracking-widest shrink-0">
            Glossary
          </span>
          {Object.entries(schema.glossary).map(([term, def]) => (
            <div
              key={term}
              className="flex items-center gap-1.5 shrink-0 text-[10px] font-mono"
            >
              <span className="text-coral-500">{term}</span>
              <span className="text-zinc-700">→</span>
              <span className="text-zinc-500 max-w-48 truncate">{def}</span>
            </div>
          ))}
        </div>
      )}

      {/* Explorer takes the rest */}
      <div className="flex-1 min-h-0">
        <SchemaExplorer
          tables={schema.tables}
          recentColumns={new Set()}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          compact={false}
        />
      </div>
    </div>
  );
}
