import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store";
import { apiLogin } from "../api";
import { useT } from "../i18n";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();
  const { t } = useT();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await apiLogin(username, password);
      login(res.token, res.user);
      navigate("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>{t("app.title")}</h1>
        <p className="login-subtitle">{t("app.subtitle")}</p>

        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder={t("login.username")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
          <input
            type="password"
            placeholder={t("login.password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <div className="error-msg">{error}</div>}
          <button type="submit" disabled={loading}>
            {loading ? "..." : t("login.signIn")}
          </button>
        </form>
      </div>
    </div>
  );
}
