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
  share_token: string | null;
  is_public: boolean;
}

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onDebate: () => void;
  onShare: (id: string, enabled: boolean) => void;
  open: boolean;
  onClose: () => void;
}

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, onDebate, onShare, open, onClose }: Props) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { lang, setLang, t } = useT();
  const { theme, toggleTheme } = useTheme();
  const [showAdmin, setShowAdmin] = useState(false);
  const [showReports, setShowReports] = useState(false);
  const [shareOpenId, setShareOpenId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const isAdmin = user?.username === "davidc";

  function handleShareToggle(conv: Conversation) {
    onShare(conv.id, !conv.is_public);
  }

  function handleCopy(convId: string, url: string) {
    navigator.clipboard.writeText(url).then(() => {
      setCopiedId(convId);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

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
            <div key={c.id}>
              <div
                className={`conversation-item ${c.id === activeId ? "active" : ""}${shareOpenId === c.id ? " share-open" : ""}`}
                onClick={() => { onSelect(c.id); onClose(); }}
              >
                <span className="conv-title">
                  {c.mode === "debate" && (
                    <span className="conv-mode-badge">{lang === "zh" ? "辩论" : "Debate"}</span>
                  )}
                  {c.mode === "fast" && (
                    <span className="conv-mode-badge fast">{lang === "zh" ? "快速" : "Fast"}</span>
                  )}
                  {c.title}
                </span>
                <div className="conv-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    className={`conv-share ${c.is_public ? "active" : ""}`}
                    onClick={() => setShareOpenId(shareOpenId === c.id ? null : c.id)}
                    title={lang === "zh" ? "分享" : "Share"}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                    </svg>
                  </button>
                  <button
                    className="conv-delete"
                    onClick={() => onDelete(c.id)}
                    title={t("sidebar.delete")}
                  >
                    &times;
                  </button>
                </div>
              </div>

              {shareOpenId === c.id && (
                <div className="share-panel" onClick={(e) => e.stopPropagation()}>
                  <div className="share-panel-row">
                    <span className="share-label">
                      {c.is_public
                        ? (lang === "zh" ? "已开启分享" : "Sharing enabled")
                        : (lang === "zh" ? "未开启分享" : "Sharing disabled")}
                    </span>
                    <button
                      className={`share-toggle-btn ${c.is_public ? "enabled" : ""}`}
                      onClick={() => handleShareToggle(c)}
                    >
                      {c.is_public
                        ? (lang === "zh" ? "关闭" : "Disable")
                        : (lang === "zh" ? "开启" : "Enable")}
                    </button>
                  </div>
                  {c.is_public && c.share_token && (
                    <div className="share-url-row">
                      <input
                        className="share-url-input"
                        readOnly
                        value={`${window.location.origin}/share/${c.share_token}`}
                        onFocus={(e) => e.target.select()}
                      />
                      <button
                        className="share-copy-btn"
                        onClick={() => handleCopy(c.id, `${window.location.origin}/share/${c.share_token}`)}
                      >
                        {copiedId === c.id ? (lang === "zh" ? "已复制" : "Copied!") : (lang === "zh" ? "复制" : "Copy")}
                      </button>
                    </div>
                  )}
                </div>
              )}
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
