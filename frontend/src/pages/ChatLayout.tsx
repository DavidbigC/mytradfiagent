import { useState, useEffect, useCallback } from "react";
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
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="chat-main">
        <ChatView
          conversationId={activeId}
          onConversationCreated={handleConversationCreated}
        />
      </main>
    </div>
  );
}
