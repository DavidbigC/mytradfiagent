import { useState } from "react";
import { useAuth } from "../store";
import AdminPanel from "./AdminPanel";

interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  open: boolean;
  onClose: () => void;
}

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, open, onClose }: Props) {
  const { user, logout } = useAuth();
  const [showAdmin, setShowAdmin] = useState(false);
  const isAdmin = user?.username === "davidc";

  return (
    <>
      {open && <div className="sidebar-overlay" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={onNew}>+ New Chat</button>
        </div>

        <div className="conversation-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`conversation-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => { onSelect(c.id); onClose(); }}
            >
              <span className="conv-title">{c.title}</span>
              <button
                className="conv-delete"
                onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
                title="Delete"
              >
                &times;
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <span className="user-name">{user?.display_name || user?.username}</span>
          <div className="sidebar-actions">
            {isAdmin && (
              <button className="admin-btn" onClick={() => setShowAdmin(true)}>Admin</button>
            )}
            <button className="logout-btn" onClick={logout}>Logout</button>
          </div>
        </div>
      </aside>

      {showAdmin && <AdminPanel onClose={() => setShowAdmin(false)} />}
    </>
  );
}
