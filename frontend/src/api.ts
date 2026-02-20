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

// --- Admin ---

export async function apiCreateAccount(token: string, username: string, password: string, displayName?: string) {
  const res = await fetch(`${BASE}/api/auth/create-account`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ username, password, display_name: displayName }),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to create account");
  }
  return res.json();
}

export async function fetchTables(token: string) {
  const res = await fetch(`${BASE}/api/admin/tables`, { headers: headers(token) });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (res.status === 403) throw new Error("Admin only");
  if (!res.ok) throw new Error("Failed to fetch tables");
  return res.json();
}

export async function fetchTableInfo(token: string, table: string) {
  const res = await fetch(`${BASE}/api/admin/tables/${table}`, { headers: headers(token) });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to fetch table info");
  return res.json();
}

export async function fetchTableRows(token: string, table: string, limit = 50, offset = 0) {
  const res = await fetch(`${BASE}/api/admin/tables/${table}/rows?limit=${limit}&offset=${offset}`, {
    headers: headers(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to fetch rows");
  return res.json();
}

export async function runQuery(token: string, sql: string) {
  const res = await fetch(`${BASE}/api/admin/query`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ sql }),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Query failed");
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

export async function fetchMessages(token: string, convId: string, limit = 50): Promise<{ messages: any[]; files: any[] }> {
  const res = await fetch(`${BASE}/api/chat/conversations/${convId}/messages?limit=${limit}`, {
    headers: headers(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to load messages");
  const data = await res.json();
  // Handle both old (array) and new ({messages, files}) response shapes
  if (Array.isArray(data)) return { messages: data, files: [] };
  return data;
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

// --- User Files ---

export async function fetchUserFiles(token: string, fileType?: string) {
  const params = fileType ? `?file_type=${fileType}` : "";
  const res = await fetch(`${BASE}/api/chat/files${params}`, { headers: headers(token) });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to load files");
  return res.json();
}

// --- SSE Send ---

export interface SSECallbacks {
  onStatus: (text: string) => void;
  onDone: (data: { text: string; files: string[]; references: Array<{ num: string; url: string }> }) => void;
  onError: (error: string) => void;
  onThinking?: (data: { source: string; label: string; content: string }) => void;
}

async function _readSSEStream(res: Response, callbacks: SSECallbacks) {
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
        if (currentEvent === "thinking") {
          if (callbacks.onThinking) {
            try { callbacks.onThinking(JSON.parse(data)); } catch { /* ignore malformed */ }
          }
        } else if (currentEvent === "status") {
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
}

export function sendMessage(
  token: string,
  message: string,
  conversationId: string | null,
  callbacks: SSECallbacks,
  mode?: string,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chat/send`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ message, conversation_id: conversationId, mode: mode || null }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (res.status === 401) { callbacks.onError("UNAUTHORIZED"); return; }
      if (!res.ok) { callbacks.onError(`HTTP ${res.status}`); return; }
      await _readSSEStream(res, callbacks);
    })
    .catch((err) => {
      if (err.name !== "AbortError") callbacks.onError(err.message);
    });

  return controller;
}

// --- Active Run / Reconnect ---

export async function fetchActiveRun(token: string): Promise<{ running: boolean; conversation_id: string | null }> {
  const res = await fetch(`${BASE}/api/chat/active`, { headers: headers(token) });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Failed to check active run");
  return res.json();
}

export function subscribeStream(token: string, callbacks: SSECallbacks): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chat/stream`, {
    headers: headers(token),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (res.status === 401) { callbacks.onError("UNAUTHORIZED"); return; }
      if (res.status === 404) { callbacks.onError("NO_ACTIVE_RUN"); return; }
      if (!res.ok) { callbacks.onError(`HTTP ${res.status}`); return; }
      await _readSSEStream(res, callbacks);
    })
    .catch((err) => {
      if (err.name !== "AbortError") callbacks.onError(err.message);
    });

  return controller;
}
