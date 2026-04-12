import { useCallback, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Check, Copy } from "lucide-react";

// Warm Obsidian SQL theme — coral keywords on earth-dark background
const sqlHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#D97757", fontWeight: "600" },   // coral
  { tag: tags.typeName, color: "#C4934A" },                      // amber (types)
  { tag: tags.string, color: "#8AB8A4" },                        // sage green
  { tag: tags.number, color: "#C4934A" },                        // amber
  { tag: tags.comment, color: "#5C5048", fontStyle: "italic" },  // muted warm
  { tag: tags.operator, color: "#B0A49C" },                      // warm gray
  { tag: tags.punctuation, color: "#8C7E74" },                   // dim warm
  { tag: tags.name, color: "#E8E0D8" },                          // primary text
  { tag: tags.function(tags.name), color: "#E88B6A" },           // coral-light for functions
]);

const theme = EditorView.theme({
  "&": {
    background: "#0E0C0A",
    color: "#E8E0D8",
    height: "100%",
  },
  ".cm-editor": { background: "#0E0C0A" },
  ".cm-scroller": { background: "#0E0C0A", overflow: "auto" },
  ".cm-content": {
    caretColor: "#D97757",
    padding: "12px 0",
    fontFamily: '"IBM Plex Mono", monospace',
  },
  ".cm-line": { padding: "0 14px" },
  ".cm-gutters": {
    background: "#161210",
    color: "#5C5048",
    border: "none",
    borderRight: "1px solid #231F18",
    paddingRight: "10px",
  },
  ".cm-activeLineGutter": { background: "#231F18" },
  ".cm-activeLine": { background: "#1A1612" },
  ".cm-selectionBackground": { background: "#3D1A1040 !important" },
  "::selection": { background: "#D9775720" },
  ".cm-cursor": { borderLeftColor: "#D97757" },
}, { dark: true });

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
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-coral-500 shrink-0" />
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest">
            SQL
          </span>
        </div>
        <button
          onClick={handleCopy}
          disabled={!value}
          className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-20 disabled:cursor-not-allowed transition-all"
        >
          {copied ? (
            <>
              <Check size={11} className="text-coral-500" />
              <span className="text-coral-500 font-medium">Copied</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-hidden">
        {value ? (
          <CodeMirror
            value={value}
            extensions={extensions}
            basicSetup={{
              lineNumbers: true,
              highlightActiveLine: true,
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
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-8 h-8 rounded-full border border-zinc-800 flex items-center justify-center">
              <span className="text-zinc-700 font-mono text-sm">{"{ }"}</span>
            </div>
            <span className="text-zinc-700 text-xs font-mono tracking-wide">
              awaiting query
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
