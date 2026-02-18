import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../store";
import { fetchConversations, createConversation, deleteConversation } from "../api";
import Sidebar from "../components/Sidebar";
import ChatView from "../components/ChatView";

interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

export default function ChatLayout() {
  const { token, logout } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showDebateModal, setShowDebateModal] = useState(false);
  const [debateInput, setDebateInput] = useState("");
  const [pendingDebate, setPendingDebate] = useState<string | null>(null);
  const debateInputRef = useRef<HTMLTextAreaElement>(null);

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
      const { id } = await createConversation(token);
      setActiveId(id);
      await loadConversations();
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

  async function handleDebateSubmit() {
    const question = debateInput.trim();
    if (!question || !token) return;

    // Create a new conversation for the debate
    try {
      const { id } = await createConversation(token);
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
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="chat-main">
        <ChatView
          conversationId={activeId}
          onConversationCreated={handleConversationCreated}
          pendingDebate={pendingDebate}
          onDebateStarted={() => setPendingDebate(null)}
        />
      </main>

      {showDebateModal && (
        <div className="debate-modal-overlay" onClick={() => { setShowDebateModal(false); setDebateInput(""); }}>
          <div className="debate-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Hypothesis Debate</h3>
            <p>Enter an investment question. The system will form a hypothesis and run a multi-analyst debate with 4 AI analysts and a judge.</p>
            <textarea
              ref={debateInputRef}
              value={debateInput}
              onChange={(e) => setDebateInput(e.target.value)}
              onKeyDown={handleDebateKeyDown}
              placeholder="e.g. 600036值得买吗？/ 招商银行 vs 工商银行 / 银行板块还会涨吗？"
              rows={3}
            />
            <div className="debate-modal-actions">
              <button className="debate-cancel" onClick={() => { setShowDebateModal(false); setDebateInput(""); }}>
                Cancel
              </button>
              <button className="debate-submit" onClick={handleDebateSubmit} disabled={!debateInput.trim()}>
                Start Debate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
