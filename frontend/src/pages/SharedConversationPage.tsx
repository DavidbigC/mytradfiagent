import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { fetchSharedConversation } from "../api";
import MessageBubble from "../components/MessageBubble";

interface Message {
  role: string;
  content: string;
  created_at: string;
}

export default function SharedConversationPage() {
  const { shareToken } = useParams<{ shareToken: string }>();
  const [title, setTitle] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!shareToken) return;
    fetchSharedConversation(shareToken)
      .then((data) => {
        setTitle(data.title);
        setMessages(data.messages);
      })
      .catch((err) => {
        if (err.message === "NOT_FOUND") setNotFound(true);
      })
      .finally(() => setLoading(false));
  }, [shareToken]);

  if (loading) {
    return (
      <div className="shared-page">
        <div className="shared-loading">Loading...</div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="shared-page">
        <div className="shared-not-found">
          Conversation not found or sharing has been disabled.
        </div>
      </div>
    );
  }

  return (
    <div className="shared-page">
      <header className="shared-header">
        <h1 className="shared-title">{title}</h1>
      </header>
      <div className="shared-messages">
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            role={msg.role as "user" | "assistant"}
            content={msg.content}
          />
        ))}
      </div>
    </div>
  );
}
