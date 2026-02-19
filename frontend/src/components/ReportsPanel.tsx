import { useState, useEffect } from "react";
import { useAuth } from "../store";
import { useT } from "../i18n";
import { fetchUserFiles } from "../api";

interface FileRecord {
  filepath: string;
  filename: string;
  file_type: string | null;
  created_at: string;
  conversation_title: string;
}

interface Props {
  onClose: () => void;
}

export default function ReportsPanel({ onClose }: Props) {
  const { token } = useAuth();
  const { t } = useT();
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    fetchUserFiles(token, filter || undefined)
      .then(setFiles)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [token, filter]);

  function handleDownload(filepath: string, filename: string) {
    if (!token) return;
    fetch(`/api/chat/files/${filepath}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Download failed");
        return res.blob();
      })
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(() => {});
  }

  const filtered = search
    ? files.filter(
        (f) =>
          f.filename.toLowerCase().includes(search.toLowerCase()) ||
          f.conversation_title.toLowerCase().includes(search.toLowerCase())
      )
    : files;

  const filters: { label: string; value: string | null }[] = [
    { label: t("reports.all"), value: null },
    { label: t("reports.pdfs"), value: "pdf" },
    { label: t("reports.charts"), value: "png" },
    { label: t("reports.markdowns"), value: "md" },
  ];

  return (
    <div className="admin-overlay" onClick={onClose}>
      <div className="admin-panel-full" onClick={(e) => e.stopPropagation()}>
        <div className="admin-header">
          <div className="admin-tabs">
            {filters.map((f) => (
              <button
                key={f.value ?? "all"}
                className={filter === f.value ? "active" : ""}
                onClick={() => setFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <button className="admin-close" onClick={onClose}>
            &times;
          </button>
        </div>
        <div className="reports-body">
          <input
            className="reports-search"
            type="text"
            placeholder="Search..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {loading ? (
            <div className="table-placeholder">{t("admin.loading")}</div>
          ) : filtered.length === 0 ? (
            <div className="table-placeholder">{t("reports.empty")}</div>
          ) : (
            <div className="reports-list">
              {filtered.map((f, i) => (
                <div key={i} className="report-item" onClick={() => handleDownload(f.filepath, f.filename)}>
                  <div className="report-icon">
                    {f.file_type === "pdf" ? "PDF" : f.file_type === "png" ? "IMG" : "MD"}
                  </div>
                  <div className="report-info">
                    <div className="report-name">{f.filename}</div>
                    <div className="report-meta">
                      {new Date(f.created_at).toLocaleDateString()} &middot; {t("reports.from")} {f.conversation_title}
                    </div>
                  </div>
                  {f.file_type === "png" && (
                    <img
                      className="report-thumb"
                      src={`/api/chat/files/${f.filepath}?token=${token}`}
                      alt=""
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
