import { useCallback, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download, TableProperties } from "lucide-react";

interface Props {
  columns: string[];
  rows: Record<string, unknown>[];
}

const PAGE_SIZE = 25;
type SortDir = "asc" | "desc" | null;

function cellStr(v: unknown): string {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function exportCsv(columns: string[], rows: Record<string, unknown>[]) {
  const header = columns.map((c) => JSON.stringify(c)).join(",");
  const body = rows
    .map((r) => columns.map((c) => JSON.stringify(cellStr(r[c]))).join(","))
    .join("\n");
  const blob = new Blob([header + "\n" + body], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "results.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export default function ResultTable({ columns, rows }: Props) {
  const [page, setPage] = useState(0);
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const sorted = useMemo(() => {
    if (!sortCol || !sortDir) return rows;
    return [...rows].sort((a, b) => {
      const av = cellStr(a[sortCol]);
      const bv = cellStr(b[sortCol]);
      const na = Number(av), nb = Number(bv);
      const cmp = !isNaN(na) && !isNaN(nb) ? na - nb : av.localeCompare(bv);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortCol, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleSort = useCallback(
    (col: string) => {
      if (sortCol !== col) { setSortCol(col); setSortDir("asc"); }
      else if (sortDir === "asc") setSortDir("desc");
      else { setSortCol(null); setSortDir(null); }
      setPage(0);
    },
    [sortCol, sortDir]
  );

  if (!columns.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 bg-zinc-900 rounded-lg border border-zinc-800">
        <TableProperties size={22} className="text-zinc-700" />
        <span className="text-zinc-600 text-xs font-mono tracking-wide">no results yet</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/70 shrink-0" />
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest">
            Results
          </span>
          <span className="px-1.5 py-0.5 rounded-sm bg-zinc-800 text-zinc-300 text-[11px] font-mono">
            {rows.length.toLocaleString()} row{rows.length !== 1 ? "s" : ""}
          </span>
        </div>
        <button
          onClick={() => exportCsv(columns, sorted)}
          className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-all"
        >
          <Download size={11} />
          <span>CSV</span>
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm border-collapse">
          <thead className="sticky top-0 bg-zinc-900 z-10">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  onClick={() => handleSort(col)}
                  className="px-3 py-2 text-left text-[10px] font-semibold text-zinc-500 uppercase tracking-wider border-b border-zinc-800 cursor-pointer hover:text-zinc-200 hover:bg-zinc-800/60 select-none whitespace-nowrap transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    {col}
                    {sortCol === col ? (
                      sortDir === "asc"
                        ? <ArrowUp size={9} className="text-coral-500" />
                        : <ArrowDown size={9} className="text-coral-500" />
                    ) : (
                      <ArrowUpDown size={9} className="opacity-20" />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-zinc-800/40 hover:bg-zinc-800/30 transition-colors"
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className="px-3 py-1.5 font-mono text-[11px] text-zinc-300 whitespace-nowrap max-w-xs truncate"
                    title={cellStr(row[col])}
                  >
                    {row[col] === null || row[col] === undefined ? (
                      <span className="text-zinc-700 italic">NULL</span>
                    ) : (
                      cellStr(row[col])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-zinc-800 shrink-0">
          <span className="text-[11px] text-zinc-600 font-mono">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 disabled:opacity-20 disabled:cursor-not-allowed transition-all"
            >
              <ChevronLeft size={13} />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 disabled:opacity-20 disabled:cursor-not-allowed transition-all"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
