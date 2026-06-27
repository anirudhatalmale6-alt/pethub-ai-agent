const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }
  return res.json();
}

export async function login(username: string, password: string) {
  const data = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  localStorage.setItem("token", data.token);
  localStorage.setItem("user", JSON.stringify(data));
  return data;
}

export async function register(username: string, password: string) {
  const data = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  localStorage.setItem("token", data.token);
  localStorage.setItem("user", JSON.stringify(data));
  return data;
}

export function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
}

export async function listConversations() {
  return apiFetch("/api/chat/conversations");
}

export async function createConversation(title?: string) {
  return apiFetch("/api/chat/conversations", {
    method: "POST",
    body: JSON.stringify({ title: title || "New conversation" }),
  });
}

export async function getMessages(conversationId: string) {
  return apiFetch(`/api/chat/conversations/${conversationId}/messages`);
}

export async function deleteConversation(conversationId: string) {
  return apiFetch(`/api/chat/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export async function approveToolExecution(executionId: string, approved: boolean) {
  return apiFetch(`/api/chat/tool-executions/${executionId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved }),
  });
}

export async function listWorkspaces() {
  return apiFetch("/api/workspaces");
}

export async function createWorkspace(data: { name: string; domain: string; wp_url?: string; wp_user?: string; wp_password?: string; description?: string; affiliate_tag?: string }) {
  return apiFetch("/api/workspaces", { method: "POST", body: JSON.stringify(data) });
}

export async function switchWorkspace(workspace: string) {
  return apiFetch("/api/workspaces/switch", { method: "POST", body: JSON.stringify({ workspace }) });
}

export async function deleteWorkspace(id: string) {
  return apiFetch(`/api/workspaces/${id}`, { method: "DELETE" });
}

export function streamMessage(conversationId: string, message: string, onEvent: (event: { type: string; data: any }) => void) {
  const token = getToken();
  const url = `${API_URL}/api/chat/conversations/${conversationId}/messages`;

  fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message }),
  }).then(async (response) => {
    if (!response.ok) {
      onEvent({ type: "error", data: { message: "Failed to send message" } });
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) return;

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
          const dataStr = line.slice(6).trim();
          try {
            const data = JSON.parse(dataStr);
            onEvent({ type: currentEvent || "message", data });
          } catch {
            // skip malformed data
          }
        }
      }
    }
  });
}
