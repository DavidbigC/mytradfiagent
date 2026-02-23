import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./store";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import ChatLayout from "./pages/ChatLayout";
import GuidancePage from "./pages/GuidancePage";
import ShowcasePage from "./pages/ShowcasePage";
import SharedConversationPage from "./pages/SharedConversationPage";

export default function App() {
  const { token } = useAuth();

  return (
    <Routes>
      <Route path="/" element={token ? <ChatLayout /> : <LandingPage />} />
      <Route path="/login" element={token ? <Navigate to="/" /> : <LoginPage />} />
      <Route path="/guidance" element={<GuidancePage />} />
      <Route path="/showcase" element={<ShowcasePage />} />
      <Route path="/share/:shareToken" element={<SharedConversationPage />} />
      <Route path="/*" element={token ? <ChatLayout /> : <Navigate to="/" />} />
    </Routes>
  );
}
