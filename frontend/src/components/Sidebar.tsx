import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store";
import { useT, useTheme } from "../i18n";
import AdminPanel from "./AdminPanel";
import ReportsPanel from "./ReportsPanel";

interface Conversation {
  id: string;
  title: string;
  updated_at: string;
  mode: string;
}

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onDebate: () => void;
  open: boolean;
  onClose: () => void;
}

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, onDebate, open, onClose }: Props) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { lang, setLang, t } = useT();
  const { theme, toggleTheme } = useTheme();
  const [showAdmin, setShowAdmin] = useState(false);
  const [showReports, setShowReports] = useState(false);
  const isAdmin = user?.username === "davidc";

  return (
    <>
      {open && <div className="sidebar-overlay" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-brand">
          <span className="sidebar-brand-name">金融研究智能体</span>
        </div>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={onNew}>{t("sidebar.newChat")}</button>
          <button className="debate-btn" onClick={onDebate}>{t("sidebar.debate")}</button>
          <button className="reports-btn" onClick={() => setShowReports(true)}>{t("sidebar.reports")}</button>
        </div>

        <div className="conversation-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`conversation-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => { onSelect(c.id); onClose(); }}
            >
              <span className="conv-title">
                {c.mode === "debate" && (
                  <span className="conv-mode-badge">{lang === "zh" ? "辩论" : "Debate"}</span>
                )}
                {c.title}
              </span>
              <button
                className="conv-delete"
                onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
                title={t("sidebar.delete")}
              >
                &times;
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-links">
          <button className="sidebar-link-btn" onClick={() => navigate("/guidance")}>
            📚 {t("sidebar.guide") || "User Guide"}
          </button>
          <button className="sidebar-link-btn" onClick={() => navigate("/showcase")}>
            ✨ {t("sidebar.showcase") || "Agent Showcase"}
          </button>
        </div>

        <div className="sidebar-footer">
          <span className="user-name">{user?.display_name || user?.username}</span>
          <div className="sidebar-actions">
            <button className="theme-toggle" onClick={toggleTheme} title={theme === "light" ? "Switch to dark" : "Switch to light"}>
              {theme === "light" ? "🌙" : "☀"}
            </button>
            <button className="lang-toggle" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
              {lang === "zh" ? "EN" : "中"}
            </button>
            {isAdmin && (
              <button className="admin-btn" onClick={() => setShowAdmin(true)}>{t("sidebar.admin")}</button>
            )}
            <button className="logout-btn" onClick={logout}>{t("sidebar.logout")}</button>
          </div>
        </div>
      </aside>

      {showAdmin && <AdminPanel onClose={() => setShowAdmin(false)} />}
      {showReports && <ReportsPanel onClose={() => setShowReports(false)} />}
    </>
  );
}
