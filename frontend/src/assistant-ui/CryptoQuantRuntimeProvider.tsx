"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
} from "@assistant-ui/react";
import { getThreadMessageText } from "./getThreadMessageText";
import type { ClaudeConfig } from "./ModelSelector";
import { ModelContext } from "./ModelSelector";
import { cryptoQuantAttachmentAdapter } from "./attachmentAdapter";

const SESSION_STORAGE_KEY = "cq_chat_session_id";

/** When true, next run() sends mode=execute (for approve → execute flow). */
export const ExecuteNextContext = React.createContext<{
  setExecuteNext: (value: boolean) => void;
}>({ setExecuteNext: () => {} });

function getOrCreateSessionId(): string {
  const existing = typeof window !== "undefined" ? window.localStorage?.getItem(SESSION_STORAGE_KEY) : null;
  if (existing) return existing;
  const id = `sess_${Math.random().toString(36).slice(2)}`;
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.setItem(SESSION_STORAGE_KEY, id);
  }
  return id;
}

export function CryptoQuantRuntimeProvider({ children }: { children: ReactNode }) {
  const sessionIdRef = useRef<string>(getOrCreateSessionId());
  const executeNextRef = useRef<boolean>(false);

  const [claudeConfig, setClaudeConfig] = useState<ClaudeConfig | null>(null);
  const [model, setModel] = useState<string>("");
  const modelRef = useRef<string>(model);
  modelRef.current = model || claudeConfig?.model || "";

  useEffect(() => {
    fetch("/api/claude-config")
      .then((r) => r.json())
      .then((data: { model?: string; models?: string[]; enabled?: boolean }) => {
        setClaudeConfig({
          enabled: data.enabled !== false,
          model: data.model ?? "",
          models: Array.isArray(data.models) ? data.models : [],
        });
        setModel(data.model ?? "");
      })
      .catch(() => setClaudeConfig({ enabled: true, model: "", models: [] }));
  }, []);

  const persistModel = useCallback(async (newModel: string) => {
    try {
      await fetch("/api/claude-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: newModel }),
      });
    } catch {
      // ignore
    }
  }, []);

  const adapter = useMemo<ChatModelAdapter>(() => ({
    async run(options: ChatModelRunOptions): Promise<ChatModelRunResult> {
      const { messages, abortSignal } = options;
      const lastUser = [...messages].reverse().find((m) => m.role === "user");
      const message = lastUser ? getThreadMessageText(lastUser as any) : "";
      if (!message.trim()) {
        return { content: [{ type: "text", text: "" }] };
      }
      const session_id = sessionIdRef.current;
      const modelVal = modelRef.current;
      const lastUserMsg = lastUser as { attachments?: readonly { name: string }[] };
      const isExecute = executeNextRef.current;
      if (isExecute) executeNextRef.current = false;
      const body: {
        message: string;
        mode: string;
        session_id: string;
        model?: string;
        attachments?: { name: string }[];
      } = {
        message: message.trim(),
        mode: isExecute ? "execute" : "auto",
        session_id,
      };
      if (modelVal) body.model = modelVal;
      if (lastUserMsg.attachments?.length) {
        body.attachments = lastUserMsg.attachments.map((a) => ({ name: a.name }));
      }
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: abortSignal,
      });
      const data = (await resp.json().catch(() => ({}))) as { reply?: string; error?: string };
      if (!resp.ok) {
        throw new Error(data.error || resp.statusText || "Chat request failed");
      }
      const text = typeof data.reply === "string" ? data.reply : "";
      return { content: [{ type: "text", text }] };
    },
  }), []);

  const runtime = useLocalRuntime(adapter, {
    adapters: { attachments: cryptoQuantAttachmentAdapter },
  });

  const executeNextContext = useMemo(
    () => ({
      setExecuteNext: (value: boolean) => {
        executeNextRef.current = value;
      },
    }),
    [],
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ExecuteNextContext.Provider value={executeNextContext}>
      <ModelContext.Provider
        value={{
          config: claudeConfig,
          model: model || claudeConfig?.model || "",
          setModel,
          persistModel,
          loading: claudeConfig === null,
        }}
      >
        {children}
      </ModelContext.Provider>
      </ExecuteNextContext.Provider>
    </AssistantRuntimeProvider>
  );
}
