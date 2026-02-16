const BASE = "";

function headers(token: string | null): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

// --- Auth ---

export async function apiRegister(username: string, password: string, displayName?: string) {
  const res = await fetch(`${BASE}/api/auth/register`, {
    method: "POST",
    headers: headers(null),
    body: JSON.stringify({ username, password, display_name: displayName }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Registration failed");
  }
  return res.json();
}

export async function apiLogin(username: string, password: string) {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: headers(null),
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Login failed");
  }
  return res.json();
}

// --- Conversations ---

export async function fetchConversations(token: string) {
  const res = await fetch(`${BASE}/api/chat/conversations`, { headers: headers(token) });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to load conversations");
  return res.json();
}

export async function createConversation(token: string) {
  const res = await fetch(`${BASE}/api/chat/conversations`, {
    method: "POST",
    headers: headers(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to create conversation");
  return res.json();
}

export async function fetchMessages(token: string, convId: string, limit = 50) {
  const res = await fetch(`${BASE}/api/chat/conversations/${convId}/messages?limit=${limit}`, {
    headers: headers(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to load messages");
  return res.json();
}

export async function deleteConversation(token: string, convId: string) {
  const res = await fetch(`${BASE}/api/chat/conversations/${convId}`, {
    method: "DELETE",
    headers: headers(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to delete conversation");
  return res.json();
}

// --- SSE Send ---

export interface SSECallbacks {
  onStatus: (text: string) => void;
  onDone: (data: { text: string; files: string[]; references: Array<{ num: string; name: string; url: string }> }) => void;
  onError: (error: string) => void;
}

export function sendMessage(
  token: string,
  message: string,
  conversationId: string | null,
  callbacks: SSECallbacks
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chat/send`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (res.status === 401) {
        callbacks.onError("UNAUTHORIZED");
        return;
      }
      if (!res.ok) {
        callbacks.onError(`HTTP ${res.status}`);
        return;
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (currentEvent === "status") {
              callbacks.onStatus(data);
            } else if (currentEvent === "done") {
              try {
                callbacks.onDone(JSON.parse(data));
              } catch {
                callbacks.onDone({ text: data, files: [], references: [] });
              }
            } else if (currentEvent === "error") {
              try {
                const parsed = JSON.parse(data);
                callbacks.onError(parsed.error || data);
              } catch {
                callbacks.onError(data);
              }
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        callbacks.onError(err.message);
      }
    });

  return controller;
}
