import { useState, useEffect } from "react";
import { useAuth } from "../store";
import {
  apiCreateAccount,
  fetchTables,
  fetchTableInfo,
  fetchTableRows,
  runQuery,
} from "../api";

type Tab = "tables" | "query" | "accounts";

interface TableInfo {
  table: string;
  row_count: number;
  columns: Array<{ name: string; type: string; nullable: boolean }>;
}

export default function AdminPanel({ onClose }: { onClose: () => void }) {
  const { token } = useAuth();
  const [tab, setTab] = useState<Tab>("tables");

  return (
    <div className="admin-overlay" onClick={onClose}>
      <div className="admin-panel-full" onClick={(e) => e.stopPropagation()}>
        <div className="admin-header">
          <div className="admin-tabs">
            <button className={tab === "tables" ? "active" : ""} onClick={() => setTab("tables")}>Tables</button>
            <button className={tab === "query" ? "active" : ""} onClick={() => setTab("query")}>SQL Query</button>
            <button className={tab === "accounts" ? "active" : ""} onClick={() => setTab("accounts")}>Create Account</button>
          </div>
          <button className="admin-close" onClick={onClose}>&times;</button>
        </div>
        <div className="admin-body">
          {tab === "tables" && <TableBrowser token={token!} />}
          {tab === "query" && <QueryRunner token={token!} />}
          {tab === "accounts" && <AccountCreator token={token!} />}
        </div>
      </div>
    </div>
  );
}

function TableBrowser({ token }: { token: string }) {
  const [tables, setTables] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [info, setInfo] = useState<TableInfo | null>(null);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const limit = 30;

  useEffect(() => {
    fetchTables(token).then(setTables).catch(() => {});
  }, [token]);

  async function selectTable(t: string) {
    setSelected(t);
    setOffset(0);
    setLoading(true);
    try {
      const [tInfo, tRows] = await Promise.all([
        fetchTableInfo(token, t),
        fetchTableRows(token, t, limit, 0),
      ]);
      setInfo(tInfo);
      setRows(tRows);
    } catch { }
    setLoading(false);
  }

  async function loadPage(newOffset: number) {
    if (!selected) return;
    setOffset(newOffset);
    setLoading(true);
    try {
      const tRows = await fetchTableRows(token, selected, limit, newOffset);
      setRows(tRows);
    } catch { }
    setLoading(false);
  }

  const columns = info?.columns.map((c) => c.name) || (rows.length > 0 ? Object.keys(rows[0]) : []);

  return (
    <div className="table-browser">
      <div className="table-list">
        {tables.map((t) => (
          <button key={t} className={`table-item ${t === selected ? "active" : ""}`} onClick={() => selectTable(t)}>
            {t}
            {info && t === selected && <span className="row-count">{info.row_count}</span>}
          </button>
        ))}
      </div>
      <div className="table-data">
        {!selected && <div className="table-placeholder">Select a table</div>}
        {selected && info && (
          <>
            <div className="table-meta">
              <strong>{info.table}</strong> — {info.row_count} rows, {info.columns.length} columns
              {info.columns.map((c) => (
                <span key={c.name} className="col-chip">{c.name} <small>{c.type}</small></span>
              ))}
            </div>
            {loading ? (
              <div className="table-placeholder">Loading...</div>
            ) : (
              <>
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          {columns.map((c) => (
                            <td key={c}>{formatCell(r[c])}</td>
                          ))}
                        </tr>
                      ))}
                      {rows.length === 0 && <tr><td colSpan={columns.length} className="table-placeholder">No rows</td></tr>}
                    </tbody>
                  </table>
                </div>
                <div className="table-pagination">
                  <button disabled={offset === 0} onClick={() => loadPage(Math.max(0, offset - limit))}>Prev</button>
                  <span>Showing {offset + 1}–{offset + rows.length} of {info.row_count}</span>
                  <button disabled={offset + limit >= info.row_count} onClick={() => loadPage(offset + limit)}>Next</button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function QueryRunner({ token }: { token: string }) {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, any>[]; count: number } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleRun() {
    if (!sql.trim()) return;
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const res = await runQuery(token, sql);
      setResult(res);
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  }

  return (
    <div className="query-runner">
      <textarea
        className="sql-input"
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        placeholder="SELECT * FROM users LIMIT 10;"
        rows={4}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); handleRun(); } }}
      />
      <div className="query-actions">
        <button onClick={handleRun} disabled={loading}>{loading ? "Running..." : "Run Query"}</button>
        <span className="query-hint">Ctrl+Enter to run. Read-only (SELECT/WITH/EXPLAIN).</span>
      </div>
      {error && <div className="error-msg">{error}</div>}
      {result && (
        <>
          <div className="query-meta">{result.count} row{result.count !== 1 ? "s" : ""} returned</div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.rows.map((r, i) => (
                  <tr key={i}>
                    {result.columns.map((c) => (
                      <td key={c}>{formatCell(r[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function AccountCreator({ token }: { token: string }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const res = await apiCreateAccount(token, username, password, displayName || undefined);
      setMessage(`Account created: ${res.username}`);
      setUsername("");
      setPassword("");
      setDisplayName("");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="account-creator">
      <form onSubmit={handleCreate}>
        <input type="text" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <input type="text" placeholder="Display Name (optional)" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <input type="password" placeholder="Password (min 6 chars)" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <div className="error-msg">{error}</div>}
        {message && <div className="success-msg">{message}</div>}
        <button type="submit" disabled={loading}>{loading ? "..." : "Create Account"}</button>
      </form>
    </div>
  );
}

function formatCell(val: any): string {
  if (val === null || val === undefined) return "NULL";
  if (typeof val === "object") {
    if (val instanceof Date) return val.toISOString();
    return JSON.stringify(val);
  }
  const s = String(val);
  return s.length > 120 ? s.slice(0, 120) + "..." : s;
}
