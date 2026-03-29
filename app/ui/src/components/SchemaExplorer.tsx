import { useState } from "react";
import { ChevronDown, ChevronRight, Database, Key, Link, Table2 } from "lucide-react";
import type { SchemaTable } from "../types";

interface Props {
  tables: SchemaTable[];
  recentColumns: Set<string>; // "table.column" strings used in last query
}

function ColTypeTag({ type }: { type: string }) {
  const short = type.split("(")[0].toUpperCase();
  return (
    <span className="ml-auto text-[10px] font-mono text-zinc-600 shrink-0">
      {short}
    </span>
  );
}

function TableNode({
  table,
  recentColumns,
}: {
  table: SchemaTable;
  recentColumns: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const hasHighlight = table.columns.some((c) =>
    recentColumns.has(`${table.name}.${c.name}`)
  );

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded hover:bg-zinc-800 transition-colors text-left group ${
          hasHighlight ? "text-zinc-200" : "text-zinc-400"
        }`}
      >
        {open ? (
          <ChevronDown size={12} className="shrink-0 text-zinc-500" />
        ) : (
          <ChevronRight size={12} className="shrink-0 text-zinc-500" />
        )}
        <Table2 size={13} className="shrink-0 text-zinc-500" />
        <span className="text-xs font-medium truncate">{table.name}</span>
        {table.row_count !== undefined && (
          <span className="ml-auto text-[10px] font-mono text-zinc-600 shrink-0">
            ~{table.row_count.toLocaleString()}
          </span>
        )}
      </button>

      {open && (
        <div className="ml-5 border-l border-zinc-800 pl-2 mb-1">
          {table.columns.map((col) => {
            const key = `${table.name}.${col.name}`;
            const highlighted = recentColumns.has(key);
            return (
              <div
                key={col.name}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                  highlighted
                    ? "text-blue-400 bg-blue-950/30"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {col.is_primary_key ? (
                  <Key size={10} className="shrink-0 text-amber-500" />
                ) : col.is_foreign_key ? (
                  <Link size={10} className="shrink-0 text-violet-400" />
                ) : (
                  <span className="w-2.5 shrink-0" />
                )}
                <span className="font-mono truncate">{col.name}</span>
                <ColTypeTag type={col.type} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function SchemaExplorer({ tables, recentColumns }: Props) {
  const [search, setSearch] = useState("");

  const filtered = search.trim()
    ? tables.filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) ||
          t.columns.some((c) =>
            c.name.toLowerCase().includes(search.toLowerCase())
          )
      )
    : tables;

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-r border-zinc-800">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-3 border-b border-zinc-800 shrink-0">
        <Database size={14} className="text-zinc-500 shrink-0" />
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          Schema
        </span>
        <span className="ml-auto text-[10px] font-mono text-zinc-600">
          {tables.length} tables
        </span>
      </div>

      {/* Search */}
      <div className="px-2 py-2 border-b border-zinc-800 shrink-0">
        <input
          type="text"
          placeholder="Filter tables / columns…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2 py-1.5 rounded bg-zinc-800 border border-zinc-700 text-xs text-zinc-300 placeholder-zinc-600 focus:outline-none focus:border-blue-600 transition-colors"
        />
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto px-1 py-1">
        {filtered.length === 0 ? (
          <div className="px-3 py-4 text-xs text-zinc-600 text-center">
            {tables.length === 0 ? "No schema loaded" : "No matches"}
          </div>
        ) : (
          filtered.map((t) => (
            <TableNode key={t.name} table={t} recentColumns={recentColumns} />
          ))
        )}
      </div>
    </div>
  );
}
