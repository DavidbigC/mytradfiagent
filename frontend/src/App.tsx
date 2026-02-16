import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./store";
import LoginPage from "./pages/LoginPage";
import ChatLayout from "./pages/ChatLayout";

export default function App() {
  const { token } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/" /> : <LoginPage />} />
      <Route path="/*" element={token ? <ChatLayout /> : <Navigate to="/login" />} />
    </Routes>
  );
}
