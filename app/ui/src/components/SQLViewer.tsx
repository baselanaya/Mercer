import { useCallback, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Check, Copy } from "lucide-react";

// Electric-blue keyword theme
const sqlHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#3b82f6", fontWeight: "600" },
  { tag: tags.typeName, color: "#a78bfa" },
  { tag: tags.string, color: "#34d399" },
  { tag: tags.number, color: "#fb923c" },
  { tag: tags.comment, color: "#52525b", fontStyle: "italic" },
  { tag: tags.operator, color: "#94a3b8" },
  { tag: tags.punctuation, color: "#94a3b8" },
  { tag: tags.name, color: "#e4e4e7" },
]);

const theme = EditorView.theme({
  "&": { background: "#18181b", color: "#e4e4e7" },
  ".cm-content": { caretColor: "#3b82f6", padding: "12px 0" },
  ".cm-line": { padding: "0 12px" },
  ".cm-gutters": {
    background: "#18181b",
    color: "#3f3f46",
    border: "none",
    borderRight: "1px solid #27272a",
    paddingRight: "8px",
  },
  ".cm-activeLineGutter": { background: "#27272a" },
  ".cm-selectionBackground": { background: "#1d4ed820 !important" },
  "::selection": { background: "#1d4ed840" },
});

const extensions = [
  sql(),
  syntaxHighlighting(sqlHighlight),
  theme,
  EditorView.lineWrapping,
  EditorView.editable.of(false),
];

interface Props {
  value: string;
}

export default function SQLViewer({ value }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [value]);

  return (
    <div className="flex flex-col h-full bg-zinc-900 rounded-lg border border-zinc-800 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 shrink-0">
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          SQL
        </span>
        <button
          onClick={handleCopy}
          disabled={!value}
          className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              Copy
            </>
          )}
        </button>
      </div>

      <div className="flex-1 overflow-hidden">
        {value ? (
          <CodeMirror
            value={value}
            extensions={extensions}
            basicSetup={{
              lineNumbers: true,
              highlightActiveLine: false,
              foldGutter: false,
              dropCursor: false,
              allowMultipleSelections: false,
              indentOnInput: false,
              bracketMatching: true,
              autocompletion: false,
              rectangularSelection: false,
              crosshairCursor: false,
              highlightSelectionMatches: false,
              closeBrackets: false,
              searchKeymap: false,
              completionKeymap: false,
              lintKeymap: false,
            }}
            style={{ height: "100%" }}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <span className="text-zinc-600 text-sm font-mono">
              — awaiting query —
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
