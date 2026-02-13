"use client";

import React from "react";
import type { OrderRow } from "./orderUtils";

function sideLabelAndColor(direct: string): { label: string; color: string } {
  const d = direct.trim().toLowerCase();
  if (d === "long" || d === "buy") return { label: "Long", color: "#4caf50" };
  if (d === "short" || d === "sell") return { label: "Short", color: "#ef5350" };
  if (d === "close") return { label: "Close", color: "#ffb300" };
  return { label: direct || "—", color: "var(--mui-palette-text-secondary, #999)" };
}

export function OrdersTable({ rows }: { rows: OrderRow[] }) {
  if (!rows || rows.length === 0) return null;

  return (
    <div
      style={{
        marginTop: 8,
        marginBottom: 4,
        borderRadius: 10,
        border: "1px solid rgba(255,255,255,0.12)",
        background: "rgba(255,255,255,0.03)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1.2fr) minmax(0, 1.3fr) minmax(0, 0.9fr)",
          padding: "6px 10px",
          borderBottom: "1px solid rgba(255,255,255,0.08)",
          fontSize: "0.72rem",
          fontWeight: 600,
          color: "var(--mui-palette-text-secondary, #aaa)",
        }}
      >
        <span>Symbol</span>
        <span style={{ textAlign: "right" }}>Size (USDT)</span>
        <span>Side</span>
        <span style={{ textAlign: "right" }}>Lev</span>
      </div>
      <div>
        {rows.map((row, idx) => {
          const { label, color } = sideLabelAndColor(row.direct);
          return (
            <div
              key={`${row.currency}-${idx}`}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1.2fr) minmax(0, 1.3fr) minmax(0, 0.9fr)",
                padding: "4px 10px",
                fontSize: "0.74rem",
                alignItems: "center",
              }}
            >
              <span style={{ fontWeight: 500 }}>{row.currency}</span>
              <span style={{ textAlign: "right", opacity: 0.9 }}>
                {row.sizeUsdt.toFixed(2)}
              </span>
              <span style={{ color, fontWeight: 600 }}>{label}</span>
              <span style={{ textAlign: "right", opacity: 0.9 }}>
                {row.lever != null ? `${row.lever}x` : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

