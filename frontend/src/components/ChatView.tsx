import { useState, useRef, useEffect, useCallback } from "react";
import { useAuth } from "../store";
import { sendMessage, fetchMessages } from "../api";
import MessageBubble, { ThinkingData } from "./MessageBubble";
import StatusIndicator from "./StatusIndicator";
import ThinkingBlock from "./ThinkingBlock";

const REF_PATTERN = /\[references\]\s*\n([\s\S]*?)\n\s*\[\/references\]/i;
const REF_LINE_URL = /\[(\d+)\]\s*(https?:\/\/\S+)/;
const REF_LINE_PIPE = /\[(\d+)\]\s*.+?\|\s*(https?:\/\/\S+)/;
const REF_LINE_ANY = /\[(\d+)\]\s*(.+)/;

function parseReferences(text: string): { cleaned: string; refs: Array<{ num: string; url: string }> } {
  const match = text.match(REF_PATTERN);
  if (!match) return { cleaned: text, refs: [] };
  const refs: Array<{ num: string; url: string }> = [];
  for (const line of match[1].trim().split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let m = trimmed.match(REF_LINE_URL);
    if (m) { refs.push({ num: m[1], url: m[2].trim() }); continue; }
    m = trimmed.match(REF_LINE_PIPE);
    if (m) { refs.push({ num: m[1], url: m[2].trim() }); continue; }
    m = trimmed.match(REF_LINE_ANY);
    if (m) {
      const urlMatch = m[2].match(/https?:\/\/\S+/);
      if (urlMatch) refs.push({ num: m[1], url: urlMatch[0].trim() });
    }
  }
  const cleaned = text.slice(0, match.index).trimEnd() + text.slice(match.index! + match[0].length);
  return { cleaned: cleaned.trimEnd(), refs };
}

interface Ref {
  num: string;
  url: string;
}

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  files?: string[];
  references?: Ref[];
  thinking?: ThinkingData[];
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
  const [thinkingBlocks, setThinkingBlocks] = useState<ThinkingData[]>([]);
  const thinkingBlocksRef = useRef<ThinkingData[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-resize textarea to fit content
  const autoResize = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, []);

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
    // Reset textarea height after clearing
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setSending(true);
    setStatus("Connecting...");
    setThinkingBlocks([]);
    thinkingBlocksRef.current = [];

    // Optimistically add user message
    setMessages((prev) => [...prev, { role: "user", content: msg }]);

    abortRef.current = sendMessage(token, msg, conversationId, {
      onStatus: (text) => setStatus(text),
      onThinking: (data) => {
        setThinkingBlocks((prev) => {
          // Merge content for same source (append), add new sources
          const existing = prev.find((t) => t.source === data.source);
          let next: ThinkingData[];
          if (existing) {
            next = prev.map((t) =>
              t.source === data.source
                ? { ...t, content: t.content + "\n" + data.content }
                : t
            );
          } else {
            next = [...prev, data];
          }
          thinkingBlocksRef.current = next;
          return next;
        });
      },
      onDone: (data) => {
        const attachedThinking = thinkingBlocksRef.current.length > 0
          ? thinkingBlocksRef.current
          : undefined;
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.text,
            files: data.files,
            references: data.references,
            thinking: attachedThinking,
          },
        ]);
        setThinkingBlocks([]);
        thinkingBlocksRef.current = [];
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
        setThinkingBlocks([]);
        thinkingBlocksRef.current = [];
        setStatus(null);
        setSending(false);
      },
    });
  }

  function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // Remove the optimistic user message (last user msg) so the user can re-send
    setMessages((prev) => {
      // Find the last user message and remove it (it was the one being processed)
      const lastUserIdx = prev.map((m) => m.role).lastIndexOf("user");
      if (lastUserIdx >= 0 && lastUserIdx === prev.length - 1) {
        return prev.slice(0, lastUserIdx);
      }
      return prev;
    });
    setThinkingBlocks([]);
    thinkingBlocksRef.current = [];
    setStatus(null);
    setSending(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Ignore Enter during IME composition (Chinese/Japanese/Korean input)
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (sending) {
        // Stop current generation first — user can then hit Enter again to send
        handleStop();
      } else {
        handleSend();
      }
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
            thinking={m.thinking}
          />
        ))}
        {thinkingBlocks.length > 0 && (
          <div className="thinking-blocks">
            {thinkingBlocks.map((t) => (
              <ThinkingBlock key={t.source} label={t.label} content={t.content} streaming={true} />
            ))}
          </div>
        )}
        {status && <StatusIndicator text={status} />}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => { setInput(e.target.value); autoResize(); }}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question... (Shift+Enter for new line)"
          rows={1}
        />
        {sending ? (
          <button className="stop-btn" onClick={handleStop}>
            Stop
          </button>
        ) : (
          <button onClick={handleSend} disabled={!input.trim()}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}
