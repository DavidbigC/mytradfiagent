import { useState, useRef, useEffect, useCallback } from "react";
import { useAuth } from "../store";
import { useT } from "../i18n";
import { sendMessage, fetchMessages, fetchActiveRun, subscribeStream, stopAgentRun } from "../api";
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
  elapsedSeconds?: number;
}

interface Props {
  conversationId: string | null;
  onConversationCreated?: () => void;
  pendingDebate?: string | null;
  onDebateStarted?: () => void;
  conversationMode?: string;
}

export default function ChatView({ conversationId, onConversationCreated, pendingDebate, onDebateStarted, conversationMode = "normal" }: Props) {
  const { token, logout } = useAuth();
  const { t, lang } = useT();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [thinkingBlocks, setThinkingBlocks] = useState<ThinkingData[]>([]);
  const thinkingBlocksRef = useRef<ThinkingData[]>([]);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [voiceState, setVoiceState] = useState<"idle" | "recording" | "transcribing">("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const [showModePicker, setShowModePicker] = useState(false);
  const pendingMsgRef = useRef<string>("");

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
      .then((data) => {
        const msgs = data.messages;
        const convFiles = data.files || [];
        // Filter to user/assistant only for display
        const display: Message[] = msgs
          .filter((m: any) => (m.role === "user" || m.role === "assistant") && m.content?.trim())
          .map((m: any) => {
            if (m.role === "assistant") {
              const { cleaned, refs } = parseReferences(m.content);
              return { role: m.role, content: cleaned, references: refs.length > 0 ? refs : undefined };
            }
            return { role: m.role, content: m.content };
          });
        // Attach conversation files to the last assistant message
        if (convFiles.length > 0) {
          const fileUrls = convFiles.map((f: any) => `/api/chat/files/${f.filepath}`);
          for (let i = display.length - 1; i >= 0; i--) {
            if (display[i].role === "assistant") {
              display[i] = { ...display[i], files: fileUrls };
              break;
            }
          }
        }
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

  // Reconnect to an in-progress agent run (survives network drops / app backgrounding)
  const reconnect = useCallback(async () => {
    if (!token || sending) return;
    try {
      const active = await fetchActiveRun(token);
      if (!active.running) return;
      // Only attach if this is our conversation (or we haven't loaded one yet)
      if (active.conversation_id && conversationId && active.conversation_id !== conversationId) return;

      setSending(true);
      setStatus(t("chat.connecting"));
      setThinkingBlocks([]);
      thinkingBlocksRef.current = [];

      abortRef.current = subscribeStream(token, {
        onStatus: (text) => setStatus(text),
        onThinking: (data) => {
          setThinkingBlocks((prev) => {
            const existing = prev.find((tb) => tb.source === data.source);
            let next: ThinkingData[];
            if (existing) {
              next = prev.map((tb) =>
                tb.source === data.source ? { ...tb, content: tb.content + "\n" + data.content } : tb
              );
            } else {
              next = [...prev, data];
            }
            thinkingBlocksRef.current = next;
            return next;
          });
        },
        onToken: (tok) => setStreamingContent((prev) => (prev ?? "") + tok),
        onDone: (data) => {
          const attachedThinking = thinkingBlocksRef.current.length > 0 ? thinkingBlocksRef.current : undefined;
          setStreamingContent(null);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: data.text, files: data.files, references: data.references, thinking: attachedThinking, elapsedSeconds: data.elapsed_seconds },
          ]);
          setThinkingBlocks([]);
          thinkingBlocksRef.current = [];
          setStatus(null);
          setSending(false);
          onConversationCreated?.();
        },
        onError: (error) => {
          if (error === "UNAUTHORIZED") { logout(); return; }
          if (error === "NO_ACTIVE_RUN") { setStatus(null); setSending(false); return; }
          setStreamingContent(null);
          setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${error}` }]);
          setThinkingBlocks([]);
          thinkingBlocksRef.current = [];
          setStatus(null);
          setSending(false);
        },
      });
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }, [token, sending, conversationId, t, onConversationCreated, logout]);

  // Check for an in-progress run when we first have a token (page load / login)
  useEffect(() => {
    reconnect();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-check when the tab becomes visible again (handles mobile network drops)
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") reconnect();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [reconnect]);

  // Auto-start debate when pendingDebate is set and conversation is ready
  useEffect(() => {
    if (pendingDebate && conversationId && token && !sending) {
      handleSend("debate", pendingDebate);
      onDebateStarted?.();
    }
  }, [pendingDebate, conversationId]);

  function handleSend(mode?: string, overrideMsg?: string) {
    const msg = overrideMsg || input.trim();
    if (!msg || !token || sending) return;

    // In debate conversations with existing messages, ask user which mode to use
    if (!mode && conversationMode === "debate" && messages.length > 0) {
      pendingMsgRef.current = msg;
      setInput("");
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      setShowModePicker(true);
      return;
    }

    setInput("");
    // Reset textarea height after clearing
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setSending(true);
    setStatus(mode === "debate" ? t("chat.debateStarting") : t("chat.connecting"));
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
      onToken: (tok) => setStreamingContent((prev) => (prev ?? "") + tok),
      onDone: (data) => {
        const attachedThinking = thinkingBlocksRef.current.length > 0
          ? thinkingBlocksRef.current
          : undefined;
        setStreamingContent(null);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.text,
            files: data.files,
            references: data.references,
            thinking: attachedThinking,
            elapsedSeconds: data.elapsed_seconds,
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
        setStreamingContent(null);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${error}` },
        ]);
        setThinkingBlocks([]);
        thinkingBlocksRef.current = [];
        setStatus(null);
        setSending(false);
      },
    }, mode);
  }

  function confirmModePicker(chosenMode?: string) {
    setShowModePicker(false);
    handleSend(chosenMode, pendingMsgRef.current);
    pendingMsgRef.current = "";
  }

  function handleStop() {
    // Cancel the server-side task first
    if (token) stopAgentRun(token).catch(() => {});
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
    setStreamingContent(null);
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

  async function handleVoiceToggle() {
    if (voiceState === "transcribing") return;

    if (voiceState === "recording") {
      mediaRecorderRef.current?.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceChunksRef.current = [];

      // Pick the best supported MIME type — iOS Safari only supports audio/mp4
      const preferredTypes = ["audio/webm", "audio/mp4", "audio/ogg"];
      const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
      const ext = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";

      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = mr;

      mr.ondataavailable = (e) => voiceChunksRef.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setVoiceState("transcribing");
        try {
          const fd = new FormData();
          fd.append("file", new Blob(voiceChunksRef.current, { type: mimeType || "audio/webm" }), `audio.${ext}`);
          const res = await fetch("/api/chat/stt", {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: fd,
          });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          // Replace each garbled extracted name with the resolved stock name + code
          let result: string = data.text;
          const replacements: Record<string, any> = data.replacements ?? {};
          for (const [extracted, match] of Object.entries(replacements)) {
            if (match && (match as any).distance <= 1) {
              const resolved = `${(match as any).stock_name}(${(match as any).stock_code}.${(match as any).exchange})`;
              result = result.split(extracted).join(resolved);
            }
          }
          setInput(result);
          setTimeout(() => autoResize(), 0);
        } catch (_err) {
          // silently ignore — user can try again
        } finally {
          setVoiceState("idle");
        }
      };

      mr.start();
      setVoiceState("recording");
    } catch (err: any) {
      setVoiceState("idle");
      // NotAllowedError = mic permission denied or non-HTTPS context
      if (err?.name === "NotAllowedError" || err?.name === "SecurityError") {
        alert("Microphone access denied. Make sure the app is served over HTTPS when using a mobile device.");
      }
    }
  }

  return (
    <div className="chat-view">
      <div className="messages-container">
        {messages.length === 0 && !status && (
          <div className="empty-chat">
            <h2>{t("chat.title")}</h2>
            <p>{t("chat.subtitle")}</p>
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
            elapsedSeconds={m.elapsedSeconds}
          />
        ))}
        {thinkingBlocks.length > 0 && (
          <div className="thinking-blocks">
            {thinkingBlocks.map((t) => (
              <ThinkingBlock key={t.source} label={t.label} content={t.content} streaming={true} />
            ))}
          </div>
        )}
        {streamingContent !== null && (
          <MessageBubble role="assistant" content={streamingContent} />
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
          placeholder={t("chat.placeholder")}
          rows={1}
        />
        <button
          className={`mic-btn${voiceState === "recording" ? " recording" : ""}`}
          onClick={handleVoiceToggle}
          disabled={voiceState === "transcribing" || sending}
          title={voiceState === "recording" ? "Stop recording" : "Voice input"}
        >
          {voiceState === "transcribing" ? "…" : voiceState === "recording" ? "⏹" : "🎤"}
        </button>
        {sending ? (
          <button className="stop-btn" onClick={handleStop}>
            {t("chat.stop")}
          </button>
        ) : (
          <button onClick={() => handleSend()} disabled={!input.trim()}>
            {t("chat.send")}
          </button>
        )}
      </div>
        {showModePicker && (
          <div className="mode-picker-overlay">
            <div className="mode-picker">
              <p className="mode-picker-prompt">
                {lang === "zh" ? "选择分析模式" : "Choose analysis mode"}
              </p>
              <div className="mode-picker-buttons">
                <button className="mode-picker-btn debate" onClick={() => confirmModePicker("debate")}>
                  ⚖ {lang === "zh" ? "假设辩论" : "Debate"}
                </button>
                <button className="mode-picker-btn normal" onClick={() => confirmModePicker(undefined)}>
                  🔍 {lang === "zh" ? "普通分析" : "Normal Analysis"}
                </button>
              </div>
              <button className="mode-picker-cancel" onClick={() => { setShowModePicker(false); setInput(pendingMsgRef.current); pendingMsgRef.current = ""; }}>
                {lang === "zh" ? "取消" : "Cancel"}
              </button>
            </div>
          </div>
        )}
    </div>
  );
}
