import React, { useEffect, useState } from "react";
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Tooltip,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

interface FundingPoint {
  fundingRate: number;
  fundingTime: number;
}

function formatFundingTimeLabel(fundingTime: number): string {
  const d = new Date(fundingTime);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[d.getUTCMonth()] ?? "";
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hour = String(d.getUTCHours()).padStart(2, "0");
  // Display as "{{Month}}:{{Day}} {{hour}}:00" in UTC (hours typically 00/08/16)
  return `${month}:${day} ${hour}:00`;
}

interface FundingHistoryDialogProps {
  symbol: string | null;
  open: boolean;
  onClose: () => void;
}

export const FundingHistoryDialog: React.FC<FundingHistoryDialogProps> = ({
  symbol,
  open,
  onClose,
}) => {
  const [points, setPoints] = useState<FundingPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !symbol) return;

    const loadHistory = async (): Promise<FundingPoint[]> => {
      const resp = await fetch(`/api/funding-rate-history?symbol=${encodeURIComponent(symbol)}&limit=200`);
      if (!resp.ok) {
        throw new Error(`Failed to load funding rate history (${resp.status})`);
      }
      const json = await resp.json();
      const rows = Array.isArray(json.rows) ? json.rows : [];
      return rows
        .map((r: any) => {
          const fr = Number(r.fundingRate);
          const ft = Number(r.fundingTime);
          if (!Number.isFinite(fr) || !Number.isFinite(ft)) return null;
          return { fundingRate: fr, fundingTime: ft };
        })
        .filter((x: FundingPoint | null): x is FundingPoint => x !== null);
    };

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        let pts = await loadHistory();

        const needsSync = () => {
          if (!pts.length) return true;
          const latest = pts[pts.length - 1];
          const nowMs = Date.now();
          const ageMs = nowMs - latest.fundingTime;
          const maxAgeMs = 3 * 24 * 60 * 60 * 1000; // 3 days
          return ageMs > maxAgeMs || ageMs < 0;
        };

        if (needsSync()) {
          try {
            await fetch("/api/sync-funding-rate-history-once", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ symbol }),
            });
            pts = await loadHistory();
          } catch {
            // Ignore sync errors and fall back to whatever we already loaded.
          }
        }

        setPoints(pts);
      } catch (e) {
        setError("Failed to load funding rate history.");
        setPoints([]);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [open, symbol]);

  if (!open || !symbol) {
    return null;
  }

  let content: React.ReactNode;
  if (loading) {
    content = <Box sx={{ p: 2 }}>Loading…</Box>;
  } else if (error) {
    content = <Box sx={{ p: 2 }}>{error}</Box>;
  } else if (!points.length) {
    content = <Box sx={{ p: 2 }}>No funding rate history available.</Box>;
  } else {
    const reversed = points.slice().reverse(); // oldest on left
    const n = reversed.length;
    const paddingLeft = 48;
    const paddingRight = 16;
    const paddingTop = 16;
    const paddingBottom = 32;
    const baseWidth = 720;
    const perPoint = 36;
    const width = Math.max(baseWidth, paddingLeft + paddingRight + (n - 1) * perPoint);
    const height = 260;

    const allValues = reversed.map((p) => p.fundingRate);
    const rawMin = Math.min(...allValues, 0);
    const rawMax = Math.max(...allValues, 0);
    const span = rawMax - rawMin || Math.abs(rawMax) || 1;
    const padding = span * 0.2;
    const minY = rawMin - padding;
    const maxY = rawMax + padding;
    const yRange = maxY - minY || 1;

    const xFor = (idx: number) =>
      paddingLeft + (n === 1 ? 0 : ((width - paddingLeft - paddingRight) * idx) / (n - 1));
    const yFor = (v: number) =>
      height - paddingBottom - ((v - minY) / yRange) * (height - paddingTop - paddingBottom);

    const pathD = reversed
      .map((p, idx) => `${idx === 0 ? "M" : "L"} ${xFor(idx)} ${yFor(p.fundingRate)}`)
      .join(" ");

    const yTicks = 4;
    const yTickValues = Array.from({ length: yTicks + 1 }, (_, i) => minY + (yRange * i) / yTicks);
    const yZero = yFor(0);

    content = (
      <Box sx={{ p: 2, overflowX: "auto" }}>
        <svg width={width} height={height}>
          {/* Axes */}
          <line
            x1={paddingLeft}
            y1={yZero}
            x2={width - paddingRight}
            y2={yZero}
            stroke="#666"
            strokeWidth={1}
          />
          <line
            x1={paddingLeft}
            y1={paddingTop}
            x2={paddingLeft}
            y2={height - paddingBottom}
            stroke="#666"
            strokeWidth={1}
          />

          {/* Y ticks & labels */}
          {yTickValues.map((v, i) => {
            const y = yFor(v);
            return (
              <g key={i}>
                <line
                  x1={paddingLeft - 4}
                  y1={y}
                  x2={width - paddingRight}
                  y2={y}
                  stroke="#444"
                  strokeWidth={0.5}
                  strokeDasharray="3 3"
                />
                <text
                  x={paddingLeft - 8}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={10}
                  fill="#aaa"
                >
                  {(v * 100).toFixed(3)}%
                </text>
              </g>
            );
          })}

          {/* Line path */}
          <path d={pathD} fill="none" stroke="#f6c343" strokeWidth={2} />

          {/* Points + tooltips */}
          {reversed.map((p, idx) => {
            const x = xFor(idx);
            const y = yFor(p.fundingRate);
            const tooltipLabel = `${formatFundingTimeLabel(p.fundingTime)} • ${(p.fundingRate * 100).toFixed(4)}%`;
            return (
              <Tooltip key={p.fundingTime} title={tooltipLabel}>
                <circle
                  cx={x}
                  cy={y}
                  r={3}
                  fill="#f6c343"
                  stroke="#000"
                  strokeWidth={0.5}
                />
              </Tooltip>
            );
          })}

          {/* X labels (every 4th point, near the X-axis at 0.000%) */}
          {reversed.map((p, idx) => {
            if (idx % 4 !== 0 && idx !== n - 1) return null;
            const x = xFor(idx);
            const label = formatFundingTimeLabel(p.fundingTime);
            const labelY = Math.min(height - paddingBottom + 14, yZero + 14);
            return (
              <text
                key={`x-${p.fundingTime}`}
                x={x}
                y={labelY}
                textAnchor="middle"
                fontSize={10}
                fill="#aaa"
              >
                {label}
              </text>
            );
          })}
        </svg>
      </Box>
    );
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        Funding rate history {symbol ? `– ${symbol}` : ""}
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent>{content}</DialogContent>
    </Dialog>
  );
};

