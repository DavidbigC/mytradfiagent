import { useState, useRef, useEffect } from "react";
import { useAuth } from "../store";
import { sendMessage, fetchMessages } from "../api";
import MessageBubble from "./MessageBubble";
import StatusIndicator from "./StatusIndicator";

const REF_PATTERN = /\[references\]\s*\n([\s\S]*?)\n\s*\[\/references\]/i;
const REF_LINE = /\[(\d+)\]\s*(.+?)\s*\|\s*(\S+)/;
const REF_LINE_NO_URL = /\[(\d+)\]\s*(.+)/;

function parseReferences(text: string): { cleaned: string; refs: Array<{ num: string; name: string; url: string }> } {
  const match = text.match(REF_PATTERN);
  if (!match) return { cleaned: text, refs: [] };
  const refs: Array<{ num: string; name: string; url: string }> = [];
  for (const line of match[1].trim().split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const m = trimmed.match(REF_LINE);
    if (m) {
      refs.push({ num: m[1], name: m[2].trim(), url: m[3].trim() });
    } else {
      const m2 = trimmed.match(REF_LINE_NO_URL);
      if (m2) refs.push({ num: m2[1], name: m2[2].trim(), url: "(tool data)" });
    }
  }
  const cleaned = text.slice(0, match.index).trimEnd() + text.slice(match.index! + match[0].length);
  return { cleaned: cleaned.trimEnd(), refs };
}

interface Ref {
  num: string;
  name: string;
  url: string;
}

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  files?: string[];
  references?: Ref[];
}

interface Props {
  conversationId: string | null;
  onConversationCreated?: () => void;
}

export default function ChatView({ conversationId, onConversationCreated }: Props) {
  const { token, logout } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load messages when conversation changes
  useEffect(() => {
    if (!conversationId || !token) {
      setMessages([]);
      return;
    }
    fetchMessages(token, conversationId)
      .then((msgs) => {
        // Filter to user/assistant only for display
        const display = msgs
          .filter((m: any) => m.role === "user" || m.role === "assistant")
          .map((m: any) => {
            if (m.role === "assistant") {
              const { cleaned, refs } = parseReferences(m.content);
              return { role: m.role, content: cleaned, references: refs.length > 0 ? refs : undefined };
            }
            return { role: m.role, content: m.content };
          });
        setMessages(display);
      })
      .catch((err) => {
        if (err.message === "UNAUTHORIZED") logout();
      });
  }, [conversationId, token]);

  // Auto scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  function handleSend() {
    const msg = input.trim();
    if (!msg || !token || sending) return;

    setInput("");
    setSending(true);
    setStatus("Connecting...");

    // Optimistically add user message
    setMessages((prev) => [...prev, { role: "user", content: msg }]);

    abortRef.current = sendMessage(token, msg, conversationId, {
      onStatus: (text) => setStatus(text),
      onDone: (data) => {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.text,
            files: data.files,
            references: data.references,
          },
        ]);
        setStatus(null);
        setSending(false);
        onConversationCreated?.();
      },
      onError: (error) => {
        if (error === "UNAUTHORIZED") {
          logout();
          return;
        }
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${error}` },
        ]);
        setStatus(null);
        setSending(false);
      },
    });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="chat-view">
      <div className="messages-container">
        {messages.length === 0 && !status && (
          <div className="empty-chat">
            <h2>Financial Research Agent</h2>
            <p>Ask about stocks, funds, bonds, or any financial topic.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble
            key={i}
            role={m.role}
            content={m.content}
            files={m.files}
            references={m.references}
          />
        ))}
        {status && <StatusIndicator text={status} />}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question..."
          rows={1}
          disabled={sending}
        />
        <button onClick={handleSend} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
