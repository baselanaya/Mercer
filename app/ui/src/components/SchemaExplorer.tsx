import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ChevronDown,
  ChevronRight,
  Database,
  GitBranch,
  Key,
  Link2,
  List,
  Search,
  Table2,
} from "lucide-react";
import type { SchemaTable } from "../types";

// ─── FK inference ─────────────────────────────────────────────────────────────
// Heuristic: column name "foo_id" → table "foo" or "foos"
function inferFKTarget(
  colName: string,
  sourceTable: string,
  tables: SchemaTable[]
): string | null {
  const lower = colName.toLowerCase();

  // Must end in a FK-suggestive suffix
  let base = lower
    .replace(/_id$/, "")
    .replace(/_fk$/, "")
    .replace(/_key$/, "")
    .replace(/_ref$/, "");

  if (base === lower || base.length < 2) return null;
  base = base.replace(/_$/, ""); // strip trailing underscore

  const candidates = tables.filter((t) => t.name !== sourceTable);
  const norm = (s: string) => s.toLowerCase().replace(/_/g, "");
  const b = norm(base);

  // Exact
  for (const t of candidates) {
    if (norm(t.name) === b) return t.name;
  }
  // Plural forms
  for (const t of candidates) {
    const tn = norm(t.name);
    if (tn === b + "s" || tn === b + "es") return t.name;
    if (tn.endsWith("s") && tn.slice(0, -1) === b) return t.name;
  }
  // Prefix match (≥ 5 chars to reduce false positives)
  if (b.length >= 5) {
    for (const t of candidates) {
      const tn = norm(t.name);
      if (tn.startsWith(b.slice(0, 5)) || b.startsWith(tn.slice(0, 5))) return t.name;
    }
  }
  return null;
}

// ─── Path builder for bezier curves between two cards ─────────────────────────
function buildPath(src: HTMLDivElement, tgt: HTMLDivElement): string {
  const dx = tgt.offsetLeft - src.offsetLeft;
  const dy = tgt.offsetTop - src.offsetTop;

  if (Math.abs(dx) >= Math.abs(dy)) {
    // Horizontal dominant
    if (dx > 0) {
      const sx = src.offsetLeft + src.offsetWidth;
      const sy = src.offsetTop + src.offsetHeight * 0.38;
      const tx = tgt.offsetLeft;
      const ty = tgt.offsetTop + tgt.offsetHeight * 0.38;
      const cp = Math.abs(dx) * 0.45;
      return `M ${sx} ${sy} C ${sx + cp} ${sy}, ${tx - cp} ${ty}, ${tx} ${ty}`;
    } else {
      const sx = src.offsetLeft;
      const sy = src.offsetTop + src.offsetHeight * 0.38;
      const tx = tgt.offsetLeft + tgt.offsetWidth;
      const ty = tgt.offsetTop + tgt.offsetHeight * 0.38;
      const cp = Math.abs(dx) * 0.45;
      return `M ${sx} ${sy} C ${sx - cp} ${sy}, ${tx + cp} ${ty}, ${tx} ${ty}`;
    }
  } else {
    // Vertical dominant
    if (dy > 0) {
      const sx = src.offsetLeft + src.offsetWidth * 0.5;
      const sy = src.offsetTop + src.offsetHeight;
      const tx = tgt.offsetLeft + tgt.offsetWidth * 0.5;
      const ty = tgt.offsetTop;
      const cp = Math.abs(dy) * 0.45;
      return `M ${sx} ${sy} C ${sx} ${sy + cp}, ${tx} ${ty - cp}, ${tx} ${ty}`;
    } else {
      const sx = src.offsetLeft + src.offsetWidth * 0.5;
      const sy = src.offsetTop;
      const tx = tgt.offsetLeft + tgt.offsetWidth * 0.5;
      const ty = tgt.offsetTop + tgt.offsetHeight;
      const cp = Math.abs(dy) * 0.45;
      return `M ${sx} ${sy} C ${sx} ${sy - cp}, ${tx} ${ty + cp}, ${tx} ${ty}`;
    }
  }
}

// ─── List view ────────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  const short = type.split("(")[0].toUpperCase();
  return (
    <span className="ml-auto shrink-0 text-[9px] font-mono text-zinc-600 tabular-nums">
      {short}
    </span>
  );
}

function TableNodeList({
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
        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-zinc-800/60 transition-colors text-left ${
          hasHighlight ? "text-coral-400" : "text-zinc-400"
        }`}
      >
        {open
          ? <ChevronDown size={11} className="shrink-0 text-zinc-600" />
          : <ChevronRight size={11} className="shrink-0 text-zinc-600" />
        }
        <Table2 size={12} className={`shrink-0 ${hasHighlight ? "text-coral-500" : "text-zinc-600"}`} />
        <span className="text-[11px] font-medium truncate flex-1">{table.name}</span>
        {table.row_count !== undefined && (
          <span className="ml-auto text-[9px] font-mono text-zinc-700 shrink-0">
            ~{table.row_count.toLocaleString()}
          </span>
        )}
      </button>

      {open && (
        <div className="ml-4 border-l border-zinc-800 pl-2 mb-1">
          {table.columns.map((col) => {
            const key = `${table.name}.${col.name}`;
            const active = recentColumns.has(key);
            return (
              <div
                key={col.name}
                className={`flex items-center gap-1.5 px-2 py-[3px] rounded text-[11px] transition-colors ${
                  active
                    ? "text-coral-400 bg-coral-950/30"
                    : "text-zinc-600 hover:text-zinc-300"
                }`}
              >
                {col.is_primary_key ? (
                  <Key size={9} className="shrink-0 text-pk" />
                ) : col.is_foreign_key ? (
                  <Link2 size={9} className="shrink-0 text-fk" />
                ) : (
                  <span className="w-2.5 shrink-0" />
                )}
                <span className="font-mono truncate flex-1">{col.name}</span>
                <TypeBadge type={col.type} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Graph view — table card ──────────────────────────────────────────────────

function TableCard({
  table,
  recentColumns,
  cardRef,
}: {
  table: SchemaTable;
  recentColumns: Set<string>;
  cardRef: (el: HTMLDivElement | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isActive = table.columns.some((c) =>
    recentColumns.has(`${table.name}.${c.name}`)
  );
  const pkCols = table.columns.filter((c) => c.is_primary_key);
  const fkCols = table.columns.filter((c) => c.is_foreign_key);
  const otherCols = table.columns.filter((c) => !c.is_primary_key && !c.is_foreign_key);

  return (
    <div
      ref={cardRef}
      className={[
        "rounded-lg border bg-zinc-900 overflow-hidden transition-all duration-300",
        isActive
          ? "border-coral-700 schema-card-active"
          : "border-zinc-800 hover:border-zinc-700",
      ].join(" ")}
    >
      {/* Card header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-zinc-800/40 transition-colors text-left"
      >
        <Table2
          size={13}
          className={`shrink-0 ${isActive ? "text-coral-500" : "text-zinc-600"}`}
        />
        <span className={`text-xs font-semibold truncate flex-1 ${isActive ? "text-coral-300" : "text-zinc-300"}`}>
          {table.name}
        </span>
        <div className="flex items-center gap-1.5 shrink-0 ml-1">
          {table.row_count !== undefined && (
            <span className="text-[9px] font-mono text-zinc-700">
              ~{table.row_count.toLocaleString()}
            </span>
          )}
          <span className="text-[9px] font-mono text-zinc-700">
            {table.columns.length}c
          </span>
          {expanded
            ? <ChevronDown size={10} className="text-zinc-600" />
            : <ChevronRight size={10} className="text-zinc-600" />
          }
        </div>
      </button>

      {/* Compact badges row (always visible) */}
      {!expanded && (
        <div className="px-3 pb-2 flex flex-wrap gap-1">
          {pkCols.map((c) => (
            <span key={c.name} className="flex items-center gap-0.5 px-1 py-0.5 rounded-sm bg-zinc-800 text-[9px] font-mono text-pk">
              <Key size={8} /> {c.name}
            </span>
          ))}
          {fkCols.slice(0, 3).map((c) => (
            <span key={c.name} className="flex items-center gap-0.5 px-1 py-0.5 rounded-sm bg-zinc-800 text-[9px] font-mono text-fk">
              <Link2 size={8} /> {c.name}
            </span>
          ))}
          {fkCols.length > 3 && (
            <span className="px-1 py-0.5 rounded-sm bg-zinc-800 text-[9px] font-mono text-zinc-600">
              +{fkCols.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Expanded column list */}
      {expanded && (
        <div className="border-t border-zinc-800 divide-y divide-zinc-800/60 max-h-52 overflow-y-auto">
          {[...pkCols, ...fkCols, ...otherCols].map((col) => {
            const key = `${table.name}.${col.name}`;
            const active = recentColumns.has(key);
            return (
              <div
                key={col.name}
                className={`flex items-center gap-2 px-3 py-1.5 text-[11px] transition-colors ${
                  active ? "bg-coral-950/30 text-coral-400" : "text-zinc-500"
                }`}
              >
                {col.is_primary_key ? (
                  <Key size={9} className="shrink-0 text-pk" />
                ) : col.is_foreign_key ? (
                  <Link2 size={9} className="shrink-0 text-fk" />
                ) : (
                  <span className="w-2.5 shrink-0" />
                )}
                <span className="font-mono truncate flex-1">{col.name}</span>
                <span className="text-[9px] font-mono text-zinc-700 shrink-0">
                  {col.type.split("(")[0].toUpperCase()}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Graph view (ERD canvas) ──────────────────────────────────────────────────

interface FKLine {
  key: string;
  d: string;
  active: boolean;
}

function GraphView({
  tables,
  recentColumns,
  search,
}: {
  tables: SchemaTable[];
  recentColumns: Set<string>;
  search: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const [lines, setLines] = useState<FKLine[]>([]);
  const [svgHeight, setSvgHeight] = useState(0);

  const filtered = search.trim()
    ? tables.filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) ||
          t.columns.some((c) => c.name.toLowerCase().includes(search.toLowerCase()))
      )
    : tables;

  const recomputeLines = useCallback(() => {
    if (!containerRef.current) return;

    setSvgHeight(containerRef.current.scrollHeight);

    const newLines: FKLine[] = [];
    const seen = new Set<string>();

    for (const table of tables) {
      for (const col of table.columns) {
        if (!col.is_foreign_key) continue;
        const targetName = inferFKTarget(col.name, table.name, tables);
        if (!targetName) continue;

        const lineKey = [table.name, targetName].sort().join("↔");
        if (seen.has(lineKey)) continue;
        seen.add(lineKey);

        const srcCard = cardRefs.current.get(table.name);
        const tgtCard = cardRefs.current.get(targetName);
        if (!srcCard || !tgtCard) continue;

        const d = buildPath(srcCard, tgtCard);
        const active =
          recentColumns.has(`${table.name}.${col.name}`) ||
          table.columns.some((c) => recentColumns.has(`${targetName}.${c.name}`));

        newLines.push({ key: `${table.name}.${col.name}`, d, active });
      }
    }

    // Cap at 30 lines; active ones shown first
    newLines.sort((a, b) => (b.active ? 1 : 0) - (a.active ? 1 : 0));
    setLines(newLines.slice(0, 30));
  }, [tables, recentColumns]);

  // Recompute after layout with ResizeObserver
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(() => recomputeLines());
    ro.observe(containerRef.current);
    recomputeLines();
    return () => ro.disconnect();
  }, [recomputeLines]);

  // Recompute when expanded state changes (card ref sizes change)
  const handleCardRef = useCallback(
    (name: string) => (el: HTMLDivElement | null) => {
      if (el) cardRefs.current.set(name, el);
      else cardRefs.current.delete(name);
      requestAnimationFrame(recomputeLines);
    },
    [recomputeLines]
  );

  return (
    <div ref={containerRef} className="relative flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
      {/* SVG FK relationship overlay */}
      {lines.length > 0 && (
        <svg
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: svgHeight || "100%",
            pointerEvents: "none",
            overflow: "visible",
            zIndex: 0,
          }}
          aria-hidden
        >
          <defs>
            <marker
              id="fk-arrow"
              viewBox="0 0 6 6"
              refX="5"
              refY="3"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 6 3 L 0 6 z" fill="#5C5048" />
            </marker>
            <marker
              id="fk-arrow-active"
              viewBox="0 0 6 6"
              refX="5"
              refY="3"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 6 3 L 0 6 z" fill="#D97757" />
            </marker>
          </defs>

          {lines.map((line) => (
            <path
              key={line.key}
              d={line.d}
              fill="none"
              stroke={line.active ? "#D97757" : "#352D24"}
              strokeWidth={line.active ? 1.5 : 1}
              strokeOpacity={line.active ? 0.7 : 0.4}
              strokeDasharray={line.active ? undefined : "5 4"}
              markerEnd={line.active ? "url(#fk-arrow-active)" : "url(#fk-arrow)"}
            />
          ))}
        </svg>
      )}

      {/* Card grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))",
          gap: "12px",
          padding: "16px",
          position: "relative",
          zIndex: 1,
        }}
      >
        {filtered.length === 0 ? (
          <div className="col-span-full flex items-center justify-center py-16 text-zinc-700 text-sm">
            No tables match "{search}"
          </div>
        ) : (
          filtered.map((t) => (
            <TableCard
              key={t.name}
              table={t}
              recentColumns={recentColumns}
              cardRef={handleCardRef(t.name)}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ─── Main SchemaExplorer ───────────────────────────────────────────────────────

export type SchemaViewMode = "list" | "graph";

interface Props {
  tables: SchemaTable[];
  recentColumns: Set<string>;
  viewMode?: SchemaViewMode;
  onViewModeChange?: (m: SchemaViewMode) => void;
  compact?: boolean; // sidebar mode
}

export default function SchemaExplorer({
  tables,
  recentColumns,
  viewMode = "list",
  onViewModeChange,
  compact = false,
}: Props) {
  const [search, setSearch] = useState("");

  const filtered = search.trim()
    ? tables.filter(
        (t) =>
          t.name.toLowerCase().includes(search.toLowerCase()) ||
          t.columns.some((c) => c.name.toLowerCase().includes(search.toLowerCase()))
      )
    : tables;

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-r border-zinc-800">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-zinc-800 shrink-0">
        <Database size={13} className="text-zinc-600 shrink-0" />
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest flex-1">
          Schema
        </span>
        <span className="text-[9px] font-mono text-zinc-700">
          {tables.length}t
        </span>

        {/* View toggle (only when not compact) */}
        {!compact && onViewModeChange && (
          <div className="flex items-center gap-0.5 ml-1 p-0.5 rounded bg-zinc-800 border border-zinc-700">
            <button
              onClick={() => onViewModeChange("list")}
              title="List view"
              className={`p-1 rounded transition-colors ${
                viewMode === "list"
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-600 hover:text-zinc-400"
              }`}
            >
              <List size={11} />
            </button>
            <button
              onClick={() => onViewModeChange("graph")}
              title="Graph view"
              className={`p-1 rounded transition-colors ${
                viewMode === "graph"
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-600 hover:text-zinc-400"
              }`}
            >
              <GitBranch size={11} />
            </button>
          </div>
        )}
      </div>

      {/* Search */}
      <div className="px-2.5 py-2 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-zinc-800 border border-zinc-700 focus-within:border-coral-700 transition-colors">
          <Search size={11} className="text-zinc-600 shrink-0" />
          <input
            type="text"
            placeholder="Filter tables / columns…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-[11px] text-zinc-300 placeholder-zinc-600 focus:outline-none"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="text-[9px] text-zinc-600 hover:text-zinc-400 font-mono"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      {viewMode === "graph" ? (
        <GraphView
          tables={tables}
          recentColumns={recentColumns}
          search={search}
        />
      ) : (
        <div className="flex-1 overflow-y-auto px-1.5 py-1">
          {filtered.length === 0 ? (
            <div className="px-3 py-6 text-[11px] text-zinc-700 text-center">
              {tables.length === 0 ? "No schema loaded" : `No matches for "${search}"`}
            </div>
          ) : (
            filtered.map((t) => (
              <TableNodeList key={t.name} table={t} recentColumns={recentColumns} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
