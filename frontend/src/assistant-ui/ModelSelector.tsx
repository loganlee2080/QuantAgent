"use client";

import React, { useCallback, useContext } from "react";

export interface ClaudeConfig {
  enabled: boolean;
  model: string;
  models: string[];
}

export const ModelContext = React.createContext<{
  config: ClaudeConfig | null;
  model: string;
  setModel: (model: string) => void;
  persistModel: (model: string) => Promise<void>;
  loading: boolean;
}>({
  config: null,
  model: "",
  setModel: () => {},
  persistModel: async () => {},
  loading: true,
});

function ModelIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, opacity: 0.9 }}
      aria-hidden
    >
      <path d="m12 3-1.5 4.5L6 8l4.5 1.5L12 14l1.5-4.5L18 8l-4.5-1.5L12 3Z" />
      <path d="m5 16 1-3 3 1-1 3-3-1Z" />
      <path d="m19 5-1 3-3-1 1-3 3 1Z" />
    </svg>
  );
}

function ChevronDown() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, opacity: 0.8 }}
      aria-hidden
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function ModelSelector({ compact }: { compact?: boolean }) {
  const { config, model, setModel, persistModel, loading } = useContext(ModelContext);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const value = e.target.value;
      setModel(value);
      void persistModel(value);
    },
    [setModel, persistModel],
  );

  if (loading || !config?.models?.length) return null;

  const displayModel = model || config.model;

  const content = (
    <>
      <ModelIcon />
      <select
        id="cq-model-select"
        value={displayModel}
        onChange={handleChange}
        style={{
          flex: compact ? "0 1 auto" : 1,
          minWidth: 0,
          border: "none",
          background: "transparent",
          color: "inherit",
          fontSize: "0.9rem",
          fontWeight: 400,
          cursor: "pointer",
          outline: "none",
          appearance: "none",
          padding: 0,
        }}
        aria-label="Select model"
      >
        {config.models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      <ChevronDown />
    </>
  );

  if (compact) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {content}
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        minHeight: 44,
        borderTop: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      {content}
    </div>
  );
}

export function useClaudeConfig(): ClaudeConfig | null {
  return useContext(ModelContext).config;
}
