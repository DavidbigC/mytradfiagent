import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../store";
import { useT } from "../i18n";
import { fetchConversations, createConversation, deleteConversation, toggleConversationShare, updateConversationMode } from "../api";
import Sidebar from "../components/Sidebar";
import ChatView from "../components/ChatView";

interface Conversation {
  id: string;
  title: string;
  updated_at: string;
  mode: string;
  share_token: string | null;
  is_public: boolean;
}

export default function ChatLayout() {
  const { token, logout } = useAuth();
  const { t, lang } = useT();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showDebateModal, setShowDebateModal] = useState(false);
  const [debateInput, setDebateInput] = useState("");
  const [pendingDebate, setPendingDebate] = useState<string | null>(null);
  const debateInputRef = useRef<HTMLTextAreaElement>(null);

  const [preferredMode, setPreferredMode] = useState<string>("fast");

  const activeConv = conversations.find((c) => c.id === activeId);
  // When a conversation is selected use its stored mode; otherwise show the user's current preference
  const activeMode = activeConv?.mode ?? preferredMode;

  const loadConversations = useCallback(async () => {
    if (!token) return;
    try {
      const convs = await fetchConversations(token);
      setConversations(convs);
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }, [token]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Focus debate input when modal opens
  useEffect(() => {
    if (showDebateModal) {
      setTimeout(() => debateInputRef.current?.focus(), 100);
    }
  }, [showDebateModal]);

  async function handleNew() {
    if (!token) return;
    try {
      const { id } = await createConversation(token, preferredMode);
      setActiveId(id);
      await loadConversations();
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }

  async function handleSwitchMode(mode: string) {
    setPreferredMode(mode);
    if (!activeId || !token) return;
    // Optimistic update — show new mode immediately
    setConversations((prev) =>
      prev.map((c) => c.id === activeId ? { ...c, mode } : c)
    );
    try {
      await updateConversationMode(token, activeId, mode);
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }

  async function handleDelete(id: string) {
    if (!token) return;
    try {
      await deleteConversation(token, id);
      if (activeId === id) setActiveId(null);
      await loadConversations();
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }

  function handleConversationCreated() {
    loadConversations();
  }

  async function handleShare(id: string, enabled: boolean) {
    if (!token) return;
    try {
      const result = await toggleConversationShare(token, id, enabled);
      setConversations((prev) =>
        prev.map((c) =>
          c.id === id ? { ...c, share_token: result.share_token, is_public: result.is_public } : c
        )
      );
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }

  async function handleDebateSubmit() {
    const question = debateInput.trim();
    if (!question || !token) return;

    // Create a new conversation for the debate
    try {
      const { id } = await createConversation(token, "debate");
      setActiveId(id);
      setPendingDebate(question);
      setDebateInput("");
      setShowDebateModal(false);
      await loadConversations();
    } catch (err: any) {
      if (err.message === "UNAUTHORIZED") logout();
    }
  }

  function handleDebateKeyDown(e: React.KeyboardEvent) {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleDebateSubmit();
    }
    if (e.key === "Escape") {
      setShowDebateModal(false);
      setDebateInput("");
    }
  }

  return (
    <div className="chat-layout">
      <button className="menu-btn" onClick={() => setSidebarOpen(true)}>
        &#9776;
      </button>

      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onDelete={handleDelete}
        onDebate={() => setShowDebateModal(true)}
        onShare={handleShare}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="chat-main">
        {activeId && activeMode === "debate" && (
          <div className="mode-indicator debate">
            ⚖ {lang === "zh" ? "辩论模式" : "Debate Mode"}
          </div>
        )}
        <ChatView
          conversationId={activeId}
          onConversationCreated={handleConversationCreated}
          pendingDebate={pendingDebate}
          onDebateStarted={() => setPendingDebate(null)}
          conversationMode={activeMode}
          onSwitchMode={handleSwitchMode}
        />
      </main>

      {showDebateModal && (
        <div className="debate-modal-overlay" onClick={() => { setShowDebateModal(false); setDebateInput(""); }}>
          <div className="debate-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("debate.title")}</h3>
            <p>{t("debate.description")}</p>
            <textarea
              ref={debateInputRef}
              value={debateInput}
              onChange={(e) => setDebateInput(e.target.value)}
              onKeyDown={handleDebateKeyDown}
              placeholder={t("debate.placeholder")}
              rows={3}
            />
            <div className="debate-modal-actions">
              <button className="debate-cancel" onClick={() => { setShowDebateModal(false); setDebateInput(""); }}>
                {t("debate.cancel")}
              </button>
              <button className="debate-submit" onClick={handleDebateSubmit} disabled={!debateInput.trim()}>
                {t("debate.start")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
