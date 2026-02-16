import { useState } from "react";
import { useAuth } from "../store";
import { apiCreateAccount } from "../api";

export default function AdminPanel({ onClose }: { onClose: () => void }) {
  const { token } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
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
    <div className="admin-overlay" onClick={onClose}>
      <div className="admin-panel" onClick={(e) => e.stopPropagation()}>
        <div className="admin-header">
          <span>Create Account</span>
          <button className="admin-close" onClick={onClose}>&times;</button>
        </div>
        <form onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            type="text"
            placeholder="Display Name (optional)"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <input
            type="password"
            placeholder="Password (min 6 chars)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <div className="error-msg">{error}</div>}
          {message && <div className="success-msg">{message}</div>}
          <button type="submit" disabled={loading}>
            {loading ? "..." : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
