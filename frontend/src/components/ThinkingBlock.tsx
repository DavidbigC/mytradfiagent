import { useState, useRef, useEffect } from "react";
import { useT } from "../i18n";

interface Props {
  label: string;
  content: string;
  streaming?: boolean;
}

export default function ThinkingBlock({ label, content, streaming = false }: Props) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(streaming);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom while streaming
  useEffect(() => {
    if (streaming && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content, streaming]);

  // Expand when streaming starts, keep state when done
  useEffect(() => {
    if (streaming) setExpanded(true);
  }, [streaming]);

  return (
    <div className={`thinking-stream${streaming ? " thinking-streaming" : ""}`}>
      <div className="thinking-header" onClick={() => setExpanded(!expanded)}>
        <span className="thinking-source">{label}</span>
        <span className="thinking-expand-hint">{expanded ? t("thinking.hide") : t("thinking.show")}</span>
      </div>
      {expanded && (
        <div className="thinking-text" ref={scrollRef}>
          {content}
        </div>
      )}
    </div>
  );
}
