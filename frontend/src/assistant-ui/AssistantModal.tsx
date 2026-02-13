"use client";

import React from "react";
import { AssistantModalPrimitive } from "@assistant-ui/react";
import { Thread } from "./Thread";

export function AssistantModal() {
  return (
    <AssistantModalPrimitive.Root>
      <AssistantModalPrimitive.Anchor
        style={{
          position: "fixed",
          right: 16,
          bottom: 16,
          zIndex: 1300,
        }}
      >
        <AssistantModalPrimitive.Trigger asChild>
          <button
            type="button"
            aria-label="Open chat"
            style={{
              width: 56,
              height: 56,
              borderRadius: "50%",
              border: "none",
              background: "var(--mui-palette-primary-main, #1976d2)",
              color: "#fff",
              cursor: "pointer",
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <ChatIcon />
          </button>
        </AssistantModalPrimitive.Trigger>
      </AssistantModalPrimitive.Anchor>
      <AssistantModalPrimitive.Content
        side="top"
        align="end"
        sideOffset={16}
        style={{
          width: "min(420px, calc(100vw - 32px))",
          height: "min(560px, calc(100vh - 120px))",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.12)",
          background: "var(--mui-palette-background-paper, #1e1e1e)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <Thread />
        </div>
      </AssistantModalPrimitive.Content>
    </AssistantModalPrimitive.Root>
  );
}

function ChatIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}
