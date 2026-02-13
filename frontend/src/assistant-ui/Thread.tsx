"use client";

import React, { useCallback } from "react";
import {
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  AuiIf,
} from "@assistant-ui/react";
import { useAui, useAuiState } from "@assistant-ui/store";
import { MarkdownTextPart } from "./MarkdownTextPart";
import { ModelSelector } from "./ModelSelector";
import { ExecuteNextContext } from "./CryptoQuantRuntimeProvider";
import { extractOrdersCsvFromMessage, parseOrdersCsv } from "./orderUtils";
import { OrdersTable } from "./OrdersTable";

const threadMaxWidth = "44rem";

const PROMPT_HINTS: { title: string; label?: string; prompt: string }[] = [
  { title: "Summarize my positions", prompt: "Summarize my current positions and PnL." },
  {
    title: "Suggest rebalance",
    label: "orders for current view",
    prompt: "Suggest a rebalance with concrete orders (currency, size_usdt, direct, lever) for my current positions.",
  },
];

function PromptHints() {
  const aui = useAui();
  const empty = useAuiState(({ thread }) => thread.messages.length === 0);
  const isRunning = useAuiState(({ thread }) => thread.isRunning);

  const handleClick = useCallback(
    (prompt: string) => {
      if (isRunning) return;
      aui.composer().setText("");
      aui.thread().append(prompt);
    },
    [aui, isRunning],
  );

  if (!empty || isRunning) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        paddingBottom: 16,
        width: "100%",
      }}
    >
      <div>
        <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 600 }}>
          Hello there!
        </h2>
        <p
          style={{
            margin: "4px 0 0",
            fontSize: "0.95rem",
            color: "var(--mui-palette-text-secondary, #888)",
          }}
        >
          How can I help you today?
        </p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {PROMPT_HINTS.map((hint, i) => (
          <button
            key={i}
            type="button"
            onClick={() => handleClick(hint.prompt)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "12px 14px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "inherit",
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.9rem",
            }}
          >
            <span style={{ fontWeight: 600 }}>{hint.title}</span>
            {hint.label && (
              <span
                style={{
                  display: "block",
                  marginTop: 2,
                  fontSize: "0.85rem",
                  color: "var(--mui-palette-text-secondary, #888)",
                }}
              >
                {hint.label}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

function isExecuteCsvMessage(text: string): boolean {
  const t = text.trim();
  return (
    t.includes("currency") &&
    t.includes("size_usdt") &&
    t.includes("direct") &&
    t.split("\n").length >= 2
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root
      data-role="user"
      style={{
        margin: 0,
        maxWidth: "100%",
        padding: "0.5rem 0.25rem",
      }}
    >
      <div
        style={{
          borderRadius: 8,
          padding: "0.5rem 0.75rem",
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.12)",
        }}
      >
        <MessagePrimitive.Parts
          components={{
            Text: ({ text }: { text?: string }) => (
              <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {isExecuteCsvMessage(text ?? "") ? "Executing orders…" : (text ?? "")}
              </span>
            ),
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function OrderApproveBar() {
  const aui = useAui();
  const isRunning = useAuiState(({ thread }) => thread.isRunning);
  const messageText = useAuiState(({ message }) => {
    const parts = (message as unknown as { parts?: { type: string; text?: string }[] }).parts ?? [];
    return parts
      .filter((p): p is { type: string; text: string } => p.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("\n\n");
  });
  const ordersCsv = extractOrdersCsvFromMessage(messageText);
  const { setExecuteNext } = React.useContext(ExecuteNextContext);

  const handleExecute = useCallback(() => {
    if (!ordersCsv || isRunning) return;
    setExecuteNext(true);
    aui.thread().append(ordersCsv);
  }, [ordersCsv, isRunning, setExecuteNext, aui]);

  const handleCancel = useCallback(() => {
    // Cancel = do nothing (no execute)
  }, []);

  if (!ordersCsv || isRunning) return null;

  return (
    <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
      <button
        type="button"
        onClick={handleExecute}
        style={{
          padding: "6px 14px",
          borderRadius: 8,
          border: "none",
          background: "var(--mui-palette-primary-main, #c4a574)",
          color: "#fff",
          cursor: "pointer",
          fontWeight: 500,
          fontSize: "0.875rem",
        }}
      >
        Execute orders
      </button>
      <button
        type="button"
        onClick={handleCancel}
        style={{
          padding: "6px 14px",
          borderRadius: 8,
          border: "1px solid rgba(255,255,255,0.3)",
          background: "transparent",
          color: "inherit",
          cursor: "pointer",
          fontSize: "0.875rem",
        }}
      >
        Cancel
      </button>
    </div>
  );
}

function AssistantMessage() {
  const messageText = useAuiState(({ message }) => {
    const parts = (message as unknown as { parts?: { type: string; text?: string }[] }).parts ?? [];
    return parts
      .filter((p): p is { type: string; text: string } => p.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("\n\n");
  });
  const ordersCsv = extractOrdersCsvFromMessage(messageText);
  const orderRows = ordersCsv ? parseOrdersCsv(ordersCsv) : [];

  return (
    <MessagePrimitive.Root
      data-role="assistant"
      style={{
        margin: 0,
        maxWidth: "100%",
        padding: "0.5rem 0.25rem",
      }}
    >
      <div style={{ padding: "0 0.25rem" }}>
        <MessagePrimitive.Parts
          components={{
            Text: (props: { type: string; text?: string }) => (
              <MarkdownTextPart type="text" text={props.text} />
            ),
          }}
        />
        <MessagePrimitive.Error />
        {orderRows.length > 0 && <OrdersTable rows={orderRows} />}
        <OrderApproveBar />
      </div>
    </MessagePrimitive.Root>
  );
}

function EmptyComposer() {
  return null;
}

export function Thread() {
  return (
    <ThreadPrimitive.Root
      className="aui-thread-root"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "inherit",
        ["--thread-max-width" as string]: threadMaxWidth,
      }}
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        style={{
          flex: 1,
          overflowY: "auto",
          overflowX: "hidden",
          padding: "1rem 1rem 0",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <ThreadPrimitive.Empty>
          <div
            style={{
              margin: "0",
              maxWidth: "100%",
              width: "100%",
              padding: "1rem",
              textAlign: "left",
              color: "var(--mui-palette-text-secondary, #888)",
            }}
          >
            <p style={{ margin: 0, fontSize: "1.1rem" }}>How can I help?</p>
            <p style={{ margin: "0.25rem 0 0", fontSize: "0.9rem" }}>
              Ask about positions or request order suggestions.
            </p>
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
            EditComposer: EmptyComposer,
          }}
        />
        <ThreadPrimitive.ViewportFooter
          style={{
            marginTop: "auto",
            paddingTop: "1rem",
            paddingBottom: "1rem",
            width: "100%",
            maxWidth: "100%",
            marginLeft: 0,
            marginRight: 0,
          }}
        >
          <PromptHints />
          <ComposerPrimitive.Root
            style={{
              display: "flex",
              flexDirection: "column",
              width: "100%",
            }}
          >
            <ComposerPrimitive.AttachmentDropzone
              style={{
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 12,
                background: "rgba(255,255,255,0.06)",
                overflow: "hidden",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 14px 0" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  <ComposerPrimitive.Attachments components={undefined} />
                </div>
              </div>
              <ComposerPrimitive.Input
                placeholder="How can I help you today?"
                rows={2}
                style={{
                  width: "100%",
                  textAlign: "left",
                  minHeight: 52,
                  padding: "14px 14px 12px",
                  border: "none",
                  background: "transparent",
                  color: "inherit",
                  font: "inherit",
                  resize: "none",
                  outline: "none",
                  fontSize: "0.95rem",
                } as any}
                aria-label="Message input"
              />
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "0 14px 12px",
                }}
              >
                <ComposerPrimitive.AddAttachment asChild>
                  <button
                    type="button"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: 36,
                      height: 36,
                      padding: 0,
                      borderRadius: 8,
                      border: "1px solid rgba(255,255,255,0.2)",
                      background: "rgba(255,255,255,0.06)",
                      color: "inherit",
                      cursor: "pointer",
                      flexShrink: 0,
                    }}
                    aria-label="Add attachment"
                  >
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M12 5v14" />
                      <path d="M5 12h14" />
                    </svg>
                  </button>
                </ComposerPrimitive.AddAttachment>
                <div style={{ flex: 1, minWidth: 0 }} />
                <ModelSelector compact />
                <AuiIf condition={(s) => !s.thread.isRunning}>
                  <ComposerPrimitive.Send asChild>
                    <button
                      type="submit"
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        width: 36,
                        height: 36,
                        padding: 0,
                        borderRadius: 8,
                        border: "none",
                        background: "var(--mui-palette-primary-main, #c4a574)",
                        color: "#fff",
                        cursor: "pointer",
                        flexShrink: 0,
                      }}
                      aria-label="Send"
                    >
                      <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden
                      >
                        <path d="m5 12 7-7 7 7" />
                        <path d="M12 19V5" />
                      </svg>
                    </button>
                  </ComposerPrimitive.Send>
                </AuiIf>
                <AuiIf condition={(s) => s.thread.isRunning}>
                  <ComposerPrimitive.Cancel asChild>
                    <button
                      type="button"
                      style={{
                        padding: "6px 14px",
                        borderRadius: 8,
                        border: "1px solid rgba(255,255,255,0.25)",
                        background: "transparent",
                        color: "inherit",
                        cursor: "pointer",
                        fontSize: "0.875rem",
                      }}
                    >
                      Stop
                    </button>
                  </ComposerPrimitive.Cancel>
                </AuiIf>
              </div>
            </ComposerPrimitive.AttachmentDropzone>
          </ComposerPrimitive.Root>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}
