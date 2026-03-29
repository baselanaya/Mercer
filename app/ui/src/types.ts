export interface ExecutionResult {
  success: boolean;
  sql: string;
  row_count: number;
  columns: string[];
  sample_rows: Record<string, unknown>[];
  error?: string;
}

export interface ReasoningTrace {
  stage_timings_ms: Record<string, number>;
  entity_matches?: Array<{
    token: string;
    table: string;
    column: string;
    score: number;
  }>;
  glossary_expansions?: Record<string, string>;
  tables_selected?: string[];
  query_plan?: Record<string, unknown>;
  candidates?: Array<{ strategy: string; score: number }>;
  correction_steps?: number;
}

export interface QueryResponse {
  sql: string | null;
  explanation: string;
  execution_result: ExecutionResult | null;
  reasoning_trace: ReasoningTrace;
  latency_ms: number;
}

export interface SchemaColumn {
  name: string;
  type: string;
  is_primary_key?: boolean;
  is_foreign_key?: boolean;
  description?: string;
}

export interface SchemaTable {
  name: string;
  columns: SchemaColumn[];
  row_count?: number;
}

export interface SchemaResponse {
  tables: SchemaTable[];
  glossary: Record<string, string>;
}

// WebSocket protocol messages
export type WsMessage =
  | { type: "started"; question: string }
  | { type: "stage_complete"; stage: string; latency_ms: number }
  | { type: "complete"; sql: string; execution_result: ExecutionResult | null; latency_ms: number }
  | { type: "error"; detail: string };

export interface HistoryEntry {
  id: string;
  question: string;
  status: "pending" | "streaming" | "done" | "error";
  stages: string[];
  result?: QueryResponse;
  errorMsg?: string;
}
