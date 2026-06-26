"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  listConversations,
  createConversation,
  getMessages,
  deleteConversation,
  approveToolExecution,
  streamMessage,
} from "@/lib/api";
import ReactMarkdown from "react-markdown";

interface Message {
  id?: string;
  role: string;
  content: string | null;
  tool_calls?: any[];
  tool_call_id?: string | null;
  isStreaming?: boolean;
}

interface ToolEvent {
  type: "tool_start" | "tool_result" | "tool_approval_required";
  tool_name: string;
  tool_call_id: string;
  arguments?: any;
  result?: any;
  status?: string;
  execution_id?: string;
  description?: string;
}

interface Props {
  user: { username: string; user_id: string; role: string };
  onLogout: () => void;
}

export default function ChatApp({ user, onLogout }: Props) {
  const [conversations, setConversations] = useState<any[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  useEffect(() => {
    listConversations().then(setConversations).catch(console.error);
  }, []);

  const loadMessages = async (convId: string) => {
    setActiveConv(convId);
    setToolEvents([]);
    try {
      const msgs = await getMessages(convId);
      setMessages(msgs);
    } catch (err) {
      console.error(err);
    }
  };

  const handleNewChat = async () => {
    try {
      const conv = await createConversation();
      setConversations((prev) => [conv, ...prev]);
      setActiveConv(conv.id);
      setMessages([]);
      setToolEvents([]);
      inputRef.current?.focus();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteConv = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConv === convId) {
        setActiveConv(null);
        setMessages([]);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;
    if (!activeConv) {
      await handleNewChat();
    }

    const convId = activeConv!;
    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    let assistantContent = "";
    const assistantMsg: Message = { role: "assistant", content: "", isStreaming: true };
    setMessages((prev) => [...prev, assistantMsg]);

    streamMessage(convId, userMsg.content!, (event) => {
      switch (event.type) {
        case "text_delta":
          assistantContent += event.data.content;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: assistantContent };
            }
            return updated;
          });
          break;

        case "tool_start":
          setToolEvents((prev) => [...prev, { type: "tool_start", ...event.data }]);
          break;

        case "tool_result":
          setToolEvents((prev) => [...prev, { type: "tool_result", ...event.data }]);
          break;

        case "tool_approval_required":
          setToolEvents((prev) => [...prev, { type: "tool_approval_required", ...event.data }]);
          break;

        case "error":
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              role: "assistant",
              content: `Error: ${event.data.message}`,
            };
            return updated;
          });
          setIsStreaming(false);
          break;

        case "done":
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, isStreaming: false };
            }
            return updated;
          });
          setIsStreaming(false);
          listConversations().then(setConversations);
          break;
      }
    });
  };

  const handleApproval = async (executionId: string, approved: boolean) => {
    try {
      const result = await approveToolExecution(executionId, approved);
      setToolEvents((prev) =>
        prev.map((te) =>
          te.execution_id === executionId
            ? { ...te, type: "tool_result", status: result.status, result: result.result }
            : te
        )
      );
    } catch (err) {
      console.error(err);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen bg-surface-950">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? "w-72" : "w-0"} transition-all duration-300 overflow-hidden flex flex-col bg-surface-900 border-r border-surface-200/5`}>
        <div className="p-4 border-b border-surface-200/5">
          <button onClick={handleNewChat} className="w-full py-2.5 px-4 bg-brand-500 hover:bg-brand-600 text-white rounded-lg font-medium text-sm transition flex items-center justify-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => loadMessages(conv.id)}
              className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer text-sm mb-1 transition ${
                activeConv === conv.id ? "bg-brand-500/10 text-brand-500" : "text-surface-300 hover:bg-surface-200/5"
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="flex-shrink-0"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
              <span className="flex-1 truncate">{conv.title}</span>
              <button
                onClick={(e) => handleDeleteConv(conv.id, e)}
                className="opacity-0 group-hover:opacity-100 text-surface-300 hover:text-red-400 transition"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
              </button>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-surface-200/5">
          <div className="flex items-center justify-between text-sm">
            <span className="text-surface-300 truncate">{user.username}</span>
            <button onClick={onLogout} className="text-surface-300 hover:text-white transition text-xs">Sign out</button>
          </div>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="h-14 border-b border-surface-200/5 flex items-center px-4 gap-3">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="text-surface-300 hover:text-white transition">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-brand-500 rounded-lg flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            </div>
            <span className="font-semibold text-white text-sm">PetHub AI Agent</span>
          </div>
          {isStreaming && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-brand-500">
              <div className="flex gap-0.5">
                <div className="w-1.5 h-1.5 bg-brand-500 rounded-full typing-dot" />
                <div className="w-1.5 h-1.5 bg-brand-500 rounded-full typing-dot" />
                <div className="w-1.5 h-1.5 bg-brand-500 rounded-full typing-dot" />
              </div>
              Processing
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 && !activeConv && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 bg-brand-500/10 rounded-2xl flex items-center justify-center mb-4">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#046bd2" strokeWidth="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
              </div>
              <h2 className="text-lg font-semibold text-white mb-2">PetHub AI Agent</h2>
              <p className="text-surface-300 text-sm max-w-md">
                Your AI operations assistant. Manage WordPress, generate content, analyse data, and automate tasks.
              </p>
              <div className="grid grid-cols-2 gap-3 mt-6 max-w-md">
                {[
                  "List all published WordPress posts",
                  "Create a draft blog post about dog nutrition",
                  "Show me the latest site pages",
                  "Generate a product comparison table",
                ].map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => { setInput(prompt); handleNewChat(); }}
                    className="text-left p-3 bg-surface-900 hover:bg-surface-800 border border-surface-200/5 rounded-lg text-xs text-surface-300 transition"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="max-w-3xl mx-auto space-y-4">
            {messages.filter((m) => m.role !== "tool").map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-brand-500 text-white"
                    : "bg-surface-900 text-surface-200 border border-surface-200/5"
                }`}>
                  {msg.role === "assistant" ? (
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown>{msg.content || ""}</ReactMarkdown>
                      {msg.isStreaming && <span className="inline-block w-2 h-4 bg-brand-500 animate-pulse ml-0.5" />}
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  )}
                </div>
              </div>
            ))}

            {/* Tool events */}
            {toolEvents.map((te, i) => (
              <div key={i} className="max-w-[85%] rounded-xl border border-surface-200/10 bg-surface-900/50 p-3 text-xs">
                {te.type === "tool_start" && (
                  <div className="flex items-center gap-2 text-yellow-400">
                    <div className="w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                    <span>Executing: <strong>{te.tool_name}</strong></span>
                  </div>
                )}
                {te.type === "tool_result" && (
                  <div className={`flex items-center gap-2 ${te.status === "completed" ? "text-green-400" : "text-red-400"}`}>
                    <span>{te.status === "completed" ? "✓" : "✕"}</span>
                    <span><strong>{te.tool_name}</strong>: {te.status}</span>
                  </div>
                )}
                {te.type === "tool_approval_required" && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-orange-400">
                      <span>⚠</span>
                      <span>Approval required: <strong>{te.tool_name}</strong></span>
                    </div>
                    <p className="text-surface-300">{te.description}</p>
                    <pre className="bg-surface-950 rounded p-2 text-surface-300 overflow-x-auto">
                      {JSON.stringify(te.arguments, null, 2)}
                    </pre>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleApproval(te.execution_id!, true)}
                        className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-md font-medium transition"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleApproval(te.execution_id!, false)}
                        className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-md font-medium transition"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-surface-200/5">
          <div className="max-w-3xl mx-auto flex gap-3">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Send a message..."
              rows={1}
              className="flex-1 resize-none px-4 py-3 bg-surface-900 border border-surface-200/10 rounded-xl text-white placeholder:text-surface-300 focus:outline-none focus:border-brand-500 transition text-sm"
              style={{ minHeight: "48px", maxHeight: "200px" }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isStreaming}
              className="px-4 py-3 bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl transition"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
