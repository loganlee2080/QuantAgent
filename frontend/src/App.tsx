import React, { useCallback, useEffect, useState } from "react";
import {
  AppBar,
  Box,
  Container,
  Grid,
  Paper,
  Tab,
  Tabs,
  Tooltip,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
} from "@mui/material";
import { PositionsTable, PositionRow } from "./components/PositionsTable";
import { OrderHistoryTable } from "./components/OrderHistoryTable";
import { MarketDataTable } from "./components/MarketDataTable";
import { AssistantSidebar } from "./assistant-ui/AssistantSidebar";
import { TradeIntentContext } from "./assistant-ui/TradeIntentContext";

interface SummaryData {
  totalWalletBalance?: string;
  totalUnrealizedProfit?: string;
  totalMarginBalance?: string;
  totalPositionInitialMargin?: string;
  availableBalance?: string;
}

interface SummaryStripProps {
  summary: SummaryData;
}

/** Set to false to hide the bottom bar (e.g. for debugging chat layout). */
const SHOW_BOTTOM_BAR = true;

interface PnlPoint {
  time: number;
  value: number;
}

const App: React.FC = () => {
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [summary, setSummary] = useState<SummaryData>({});
  const [tabIndex, setTabIndex] = useState<number>(0);
  const [pnlHistory, setPnlHistory] = useState<PnlPoint[]>([]);
  const [isPnlChartOpen, setIsPnlChartOpen] = useState(false);
  const [pnlLoading, setPnlLoading] = useState(false);
  const [pnlError, setPnlError] = useState<string | null>(null);
  const [pnlHoverIndex, setPnlHoverIndex] = useState<number | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [pendingTradeCurrencies, setPendingTradeCurrencies] = useState<string[] | null>(null);
  const [pendingChatText, setPendingChatText] = useState<string | null>(null);

  const openChatWithTrade = useCallback((currencies: string[]) => {
    const list = currencies.filter(Boolean);
    if (!list.length) return;
    setChatOpen(true);
    setPendingTradeCurrencies(list);
  }, []);

  const consumeTradeIntent = useCallback(() => {
    setPendingTradeCurrencies(null);
  }, []);

  const addTextToChat = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setChatOpen(true);
    setPendingChatText(trimmed);
  }, []);

  const consumeChatText = useCallback(() => {
    setPendingChatText(null);
  }, []);

  const unrealized = summary.totalUnrealizedProfit;
  const unrealizedNumber = unrealized !== undefined ? Number(unrealized) : NaN;
  const unrealizedColor =
    !Number.isFinite(unrealizedNumber) || unrealizedNumber === 0
      ? "text.primary"
      : unrealizedNumber > 0
        ? "success.main"
        : "error.main";

  const pnlBase = summary.totalMarginBalance ?? summary.totalWalletBalance;
  const pnlBaseNumber = pnlBase !== undefined ? Number(pnlBase) : NaN;
  const pnlPercentNumber =
    Number.isFinite(unrealizedNumber) && Number.isFinite(pnlBaseNumber) && pnlBaseNumber !== 0
      ? (unrealizedNumber / pnlBaseNumber) * 100
      : NaN;
  const pnlPercentColor =
    !Number.isFinite(pnlPercentNumber) || pnlPercentNumber === 0
      ? "text.primary"
      : pnlPercentNumber > 0
        ? "success.main"
        : "error.main";

  const fmt2 = (value: string | undefined) => {
    if (value === undefined) return "-";
    const n = Number(value);
    if (!Number.isFinite(n)) return value;
    return n.toFixed(2);
  };

  const fmt4 = (value: string | undefined) => {
    if (value === undefined) return "-";
    const n = Number(value);
    if (!Number.isFinite(n)) return value;
    return n.toFixed(4);
  };

  // Total position = sum of per-symbol position value in USDT from positions table.
  const totalPosition = positions.reduce((acc, p) => {
    const v = Number(p.positionValue);
    return Number.isFinite(v) ? acc + v : acc;
  }, 0);
  const marginBalance = summary.totalMarginBalance ?? summary.totalWalletBalance;
  const marginBalanceNum = marginBalance !== undefined ? Number(marginBalance) : NaN;
  const marginRatio =
    Number.isFinite(marginBalanceNum) && Number.isFinite(totalPosition) && totalPosition !== 0
      ? (marginBalanceNum / totalPosition) * 100
      : NaN;

  const handleOpenPnlChart = () => setIsPnlChartOpen(true);
  const handleClosePnlChart = () => setIsPnlChartOpen(false);

  // Load PNL (%) history from backend (summary.csv) when panel is opened.
  useEffect(() => {
    if (!isPnlChartOpen) return;
    const load = async () => {
      try {
        setPnlLoading(true);
        setPnlError(null);
        const resp = await fetch("/api/pnl-history?limit=200");
        if (!resp.ok) {
          throw new Error(`Failed to load PNL history (${resp.status})`);
        }
        const json = await resp.json();
        const points = Array.isArray(json.points) ? json.points : [];
        const mapped: PnlPoint[] = points
          .map((p: any) => {
            const t = Number(p.time);
            const v = Number(p.pnl_percent);
            if (!Number.isFinite(t) || !Number.isFinite(v)) return null;
            return { time: t, value: v };
          })
          .filter((x: PnlPoint | null): x is PnlPoint => x !== null);
        setPnlHistory(mapped);
      } catch (e) {
        console.error("Failed to load PNL history", e);
        setPnlError("Failed to load PNL history.");
        setPnlHistory([]);
      } finally {
        setPnlLoading(false);
      }
    };
    load();
  }, [isPnlChartOpen]);

  const SummaryStrip: React.FC = () => (
    <Paper
      elevation={3}
      sx={{
        mb: 2,
        p: 2,
        bgcolor: "background.default",
        borderRadius: 2,
      }}
    >
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          gap: 3,
          alignItems: "flex-end",
          justifyContent: "space-between",
        }}
      >
        <Box sx={{ ml: 8 }}>
          <Typography variant="subtitle2" color="text.secondary">
            Margin balance (USDT)
          </Typography>
          <Typography variant="h5">
            {fmt4(summary.totalMarginBalance ?? summary.totalWalletBalance)}
          </Typography>
        </Box>
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            PNL (USDT)
          </Typography>
          <Typography variant="h6" sx={{ color: unrealizedColor }}>
            {fmt4(unrealized)}
          </Typography>
        </Box>
        <Box>
          <Typography variant="subtitle2" color="text.secondary">
            PNL (%)
          </Typography>
          <Typography variant="h6" sx={{ color: pnlPercentColor }}>
            {Number.isFinite(pnlPercentNumber) ? `${pnlPercentNumber.toFixed(2)}%` : "-"}
          </Typography>
        </Box>
        <Box sx={{ mr: 12 }}>
          <Typography variant="subtitle2" color="text.secondary">
            Available balance (USDT)
          </Typography>
          <Typography variant="h6">
            {fmt4(summary.availableBalance)}
          </Typography>
        </Box>
      </Box>
    </Paper>
  );

  const fetchData = async () => {
    try {
      const [posResp, sumResp] = await Promise.all([fetch("/api/positions"), fetch("/api/summary")]);
      const posJson = await posResp.json();
      const sumJson = await sumResp.json();
      setPositions(posJson.positions ?? []);
      setSummary(sumJson.summary ?? {});
    } catch (e) {
      // In case backend is not running yet.
      console.error("Error fetching data", e);
    }
  };

  useEffect(() => {
    fetchData();
    const id = window.setInterval(fetchData, 15000);
    return () => window.clearInterval(id);
  }, []);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTabIndex(newValue);
  };

  useEffect(() => {
    const openMarket = () => setTabIndex(1);
    const openPositions = () => setTabIndex(0);
    window.addEventListener("cq-open-market-data" as any, openMarket as EventListener);
    window.addEventListener("cq-open-positions" as any, openPositions as EventListener);
    return () => {
      window.removeEventListener("cq-open-market-data" as any, openMarket as EventListener);
      window.removeEventListener("cq-open-positions" as any, openPositions as EventListener);
    };
  }, []);

  const tradeIntentValue = React.useMemo(
    () => ({
      pendingTradeCurrencies,
      openChatWithTrade,
      consumeTradeIntent,
      pendingChatText,
      addTextToChat,
      consumeChatText,
    }),
    [pendingTradeCurrencies, openChatWithTrade, consumeTradeIntent, pendingChatText, addTextToChat, consumeChatText],
  );

  return (
    <TradeIntentContext.Provider value={tradeIntentValue}>
      <Box sx={{ display: "flex", height: "100vh", flexDirection: "column", overflow: "hidden" }}>
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
          <AssistantSidebar
            open={chatOpen}
            onOpenChange={setChatOpen}
            defaultWidthPercent={32}
          >
          <Box sx={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {/* Scrollable content (tables) */}
            <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
              <Container maxWidth={false} sx={{ mt: 2, px: 2, pb: 0 }}>
                <Grid container spacing={2}>
                  <Grid item xs={12}>
                    {tabIndex === 0 && (
                      <PositionsTable
                        positions={positions}
                        onRefresh={fetchData}
                      />
                    )}
                    {tabIndex === 1 && <MarketDataTable />}
                  </Grid>
                </Grid>
              </Container>
            </Box>
            {/* Fixed bottom bar */}
            {SHOW_BOTTOM_BAR && (
              <Box
                sx={{
                  flexShrink: 0,
                  bgcolor: "background.paper",
                  borderTop: (theme) => `1px solid ${theme.palette.divider}`,
                }}
              >
                <Container maxWidth={false} sx={{ py: 0.75, px: 2 }}>
                  <Box sx={{ display: "flex", gap: 4, alignItems: "center", fontSize: "0.875rem" }}>
                    <Typography variant="body2" color="text.secondary">
                      Margin balance:&nbsp;
                      <Typography component="span" color="text.primary">
                        {fmt2(summary.totalMarginBalance ?? summary.totalWalletBalance)}
                      </Typography>
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      PNL:&nbsp;
                      <Typography component="span" sx={{ color: unrealizedColor }}>
                        {fmt2(unrealized)}
                      </Typography>
                    </Typography>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ cursor: "pointer", display: "flex", alignItems: "center" }}
                      onClick={handleOpenPnlChart}
                    >
                      PNL (%):&nbsp;
                      <Typography component="span" sx={{ color: pnlPercentColor }}>
                        {Number.isFinite(pnlPercentNumber) ? `${pnlPercentNumber.toFixed(2)}%` : "-"}
                      </Typography>
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Available balance:&nbsp;
                      <Typography component="span" color="text.primary">
                        {fmt2(summary.availableBalance)}
                      </Typography>
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Margin ratio:&nbsp;
                      <Tooltip
                        title="Margin balance / total position value (USDT) × 100%"
                        arrow
                      >
                        <Typography
                          component="span"
                          sx={{
                            cursor: "help",
                            color:
                              !Number.isFinite(marginRatio) || marginRatio === 0
                                ? "text.primary"
                                : marginRatio > 0
                                  ? "success.main"
                                  : "error.main",
                          }}
                        >
                          {Number.isFinite(marginRatio) ? `${marginRatio.toFixed(2)}%` : "-"}
                        </Typography>
                      </Tooltip>
                    </Typography>
                  </Box>
                </Container>
              </Box>
            )}
          </Box>
        </AssistantSidebar>
      </Box>
      {/* PNL (%) over time panel – reuse funding-history style SVG renderer */}
      <Dialog open={isPnlChartOpen} onClose={handleClosePnlChart} maxWidth="md" fullWidth>
        <DialogTitle>PNL (%) over time</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            {pnlLoading ? (
              <Typography variant="body2" color="text.secondary">
                Loading…
              </Typography>
            ) : pnlError ? (
              <Typography variant="body2" color="error">
                {pnlError}
              </Typography>
            ) : pnlHistory.length ? (
              <Box
                sx={{
                  height: 260,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  bgcolor: "background.default",
                }}
              >
                {/* Simple SVG path like FundingHistoryDialog, but for PNL (%) */}
                <Box sx={{ p: 2, overflowX: "auto" }}>
                  {(() => {
                    const reversed = pnlHistory.slice().reverse();
                    const n = reversed.length;
                    const paddingLeft = 48;
                    const paddingRight = 16;
                    const paddingTop = 16;
                    const paddingBottom = 32;
                    const baseWidth = 720;
                    const perPoint = 36;
                    const width = Math.max(baseWidth, paddingLeft + paddingRight + (n - 1) * perPoint);
                    const height = 260;

                    const allValues = reversed.map((p) => p.value);
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
                      height -
                      paddingBottom -
                      ((v - minY) / yRange) * (height - paddingTop - paddingBottom);

                    const pathD = reversed
                      .map((p, idx) => `${idx === 0 ? "M" : "L"} ${xFor(idx)} ${yFor(p.value)}`)
                      .join(" ");

                    const yTicks = 4;
                    const yTickValues = Array.from(
                      { length: yTicks + 1 },
                      (_, i) => minY + (yRange * i) / yTicks
                    );
                    const yZero = yFor(0);

                    const formatHoverTime = (ms: number): string => {
                      const d = new Date(ms);
                      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                      const month = months[d.getUTCMonth()] ?? "";
                      const day = String(d.getUTCDate()).padStart(2, "0");
                      const hour = String(d.getUTCHours()).padStart(2, "0");
                      return `${month}:${day} ${hour}:00`;
                    };

                    const handleMove = (evt: React.MouseEvent<SVGSVGElement>) => {
                      const rect = (evt.currentTarget as SVGSVGElement).getBoundingClientRect();
                      const x = evt.clientX - rect.left;
                      const usableWidth = width - paddingLeft - paddingRight;
                      const clampedX = Math.min(Math.max(x, paddingLeft), width - paddingRight);
                      const t = usableWidth > 0 ? (clampedX - paddingLeft) / usableWidth : 0;
                      const idx = Math.round(t * (n - 1));
                      if (idx >= 0 && idx < n) {
                        setPnlHoverIndex(idx);
                      }
                    };

                    const handleLeave = () => {
                      setPnlHoverIndex(null);
                    };

                    const hoverPoint =
                      pnlHoverIndex != null && pnlHoverIndex >= 0 && pnlHoverIndex < n
                        ? reversed[pnlHoverIndex]
                        : null;
                    const hoverX = hoverPoint ? xFor(pnlHoverIndex as number) : null;
                    const hoverY = hoverPoint ? yFor(hoverPoint.value) : null;

                    return (
                      <svg
                        width={width}
                        height={height}
                        onMouseMove={handleMove}
                        onMouseLeave={handleLeave}
                      >
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
                                {v.toFixed(2)}%
                              </text>
                            </g>
                          );
                        })}

                        {/* Line path */}
                        <path d={pathD} fill="none" stroke="#33D778" strokeWidth={2} />

                        {/* Crosshair + labels */}
                        {hoverPoint && hoverX != null && hoverY != null && (
                          <>
                            {/* Vertical line */}
                            <line
                              x1={hoverX}
                              y1={paddingTop}
                              x2={hoverX}
                              y2={height - paddingBottom}
                              stroke="#888"
                              strokeWidth={1}
                              strokeDasharray="4 4"
                            />
                            {/* Horizontal line */}
                            <line
                              x1={paddingLeft}
                              y1={hoverY}
                              x2={width - paddingRight}
                              y2={hoverY}
                              stroke="#888"
                              strokeWidth={1}
                              strokeDasharray="4 4"
                            />
                            {/* Point marker */}
                            <circle cx={hoverX} cy={hoverY} r={4} fill="#33D778" />
                            {/* Y value label (PNL %) */}
                            <text
                              x={width - paddingRight}
                              y={paddingTop + 14}
                              textAnchor="end"
                              fontSize={11}
                              fill="#fff"
                            >
                              {hoverPoint.value.toFixed(2)}%
                            </text>
                            {/* X time label near the X-axis */}
                            <text
                              x={hoverX}
                              y={height - paddingBottom + 18}
                              textAnchor="middle"
                              fontSize={11}
                              fill="#fff"
                            >
                              {formatHoverTime(hoverPoint.time)}
                            </text>
                          </>
                        )}
                      </svg>
                    );
                  })()}
                </Box>
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Not enough data yet to render the PNL chart.
              </Typography>
            )}
          </Box>
        </DialogContent>
      </Dialog>
    </Box>
    </TradeIntentContext.Provider>
  );
};

export default App;

