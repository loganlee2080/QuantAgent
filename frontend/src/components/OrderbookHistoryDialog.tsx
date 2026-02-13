import React, { useEffect, useRef, useState } from "react";
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { createChart, type IChartApi, type ISeriesApi, type LineData } from "lightweight-charts";

/** Normalized point: time in ms, bid and ask volumes. */
export interface OrderbookPoint {
  time: number;
  bid: number;
  ask: number;
}

interface OrderbookHistoryDialogProps {
  symbol: string | null;
  open: boolean;
  onClose: () => void;
  /** Called when spot/future summary is loaded so parent can show values in table cell. */
  onSummaryLoaded?: (symbol: string, spot: string, future: string) => void;
}

/** Parse CoinGlass-style response into OrderbookPoint[]. */
function parseOrderbookResponse(json: unknown): OrderbookPoint[] {
  const obj = json as Record<string, unknown>;
  const inner = obj?.data && typeof obj.data === "object" ? (obj.data as Record<string, unknown>) : null;
  const raw =
    Array.isArray(json)
      ? json
      : Array.isArray(obj?.data)
        ? obj.data
        : Array.isArray(inner?.data)
          ? inner!.data
          : Array.isArray(inner?.list)
            ? inner!.list
            : Array.isArray(obj?.list)
              ? obj.list
              : [];
  if (!Array.isArray(raw)) return [];
  return raw
    .map((r: Record<string, unknown>) => {
      const t = r.time ?? r.timestamp ?? r.createTime ?? r.t ?? r.date ?? r.candleTime;
      const timeMs = typeof t === "number" ? (t > 1e12 ? t : t * 1000) : typeof t === "string" ? new Date(t).getTime() : 0;
      // CoinGlass uses bids_usd/bids_quantity and asks_usd/asks_quantity
      const bid = Number(
        r.bids_usd ?? r.bids_quantity ?? r.bid ?? r.bidVolume ?? r.bids ?? r.bidVol ?? r.buyVolume ?? r.longVolume ?? 0
      ) || 0;
      const ask = Number(
        r.asks_usd ?? r.asks_quantity ?? r.ask ?? r.askVolume ?? r.asks ?? r.askVol ?? r.sellVolume ?? r.shortVolume ?? 0
      ) || 0;
      if (!Number.isFinite(timeMs)) return null;
      return { time: timeMs, bid, ask };
    })
    .filter((x: OrderbookPoint | null): x is OrderbookPoint => x !== null)
    .sort((a, b) => a.time - b.time);
}

/** Format large numbers for y-axis and summary: e.g. 400000000 -> "400M", 1.2e9 -> "1.2B". */
function formatPriceHuman(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return value.toFixed(2);
}

/** Latest point as "ask X / bid Y" or "Not supported". */
function formatSummaryAskBid(points: OrderbookPoint[]): string {
  if (!points.length) return "Not supported";
  const last = points[points.length - 1];
  return `ask ${formatPriceHuman(last.ask)} / bid ${formatPriceHuman(last.bid)}`;
}

/** Convert orderbook points to Lightweight Charts line data (time in seconds). */
function toLineData(points: OrderbookPoint[], bidOrAsk: "bid" | "ask"): LineData[] {
  return points.map((p) => ({
    time: Math.floor(p.time / 1000) as LineData["time"],
    value: bidOrAsk === "bid" ? p.bid : p.ask,
  }));
}

export const OrderbookHistoryDialog: React.FC<OrderbookHistoryDialogProps> = ({
  symbol,
  open,
  onClose,
  onSummaryLoaded,
}) => {
  const [spotPoints, setSpotPoints] = useState<OrderbookPoint[]>([]);
  const [futuresPoints, setFuturesPoints] = useState<OrderbookPoint[]>([]);
  const [spotSupported, setSpotSupported] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const bidSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const askSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!open || !symbol) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setSpotSupported(null);
      try {
        const [spotResp, futuresResp] = await Promise.all([
          fetch(`/api/coinglass/orderbook-history?symbol=${encodeURIComponent(symbol)}&market=spot`),
          fetch(`/api/coinglass/orderbook-history?symbol=${encodeURIComponent(symbol)}&market=futures`),
        ]);
        const spotJson = await spotResp.json();
        const futuresJson = await futuresResp.json();

        if (!futuresResp.ok) {
          throw new Error(futuresJson?.error || `Request failed (${futuresResp.status})`);
        }
        const futuresParsed = parseOrderbookResponse(futuresJson);
        setFuturesPoints(futuresParsed);

        const spotOk = spotJson?.spotSupported !== false && spotResp.ok;
        setSpotSupported(spotOk);
        if (spotOk) {
          setSpotPoints(parseOrderbookResponse(spotJson));
        } else {
          setSpotPoints([]);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load orderbook history.");
        setSpotPoints([]);
        setFuturesPoints([]);
        setSpotSupported(false);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [open, symbol]);

  // Notify parent of summary so table cell can show "ask X / bid Y"
  useEffect(() => {
    if (!symbol || !onSummaryLoaded || loading) return;
    const spotLine = spotSupported && spotPoints.length > 0 ? formatSummaryAskBid(spotPoints) : "Not supported";
    const futureLine = futuresPoints.length > 0 ? formatSummaryAskBid(futuresPoints) : "ask — / bid —";
    onSummaryLoaded(symbol, spotLine, futureLine);
  }, [symbol, onSummaryLoaded, loading, spotSupported, spotPoints, futuresPoints]);

  // Chart displays spot when supported, else futures (4h)
  const chartPoints = spotSupported && spotPoints.length > 0 ? spotPoints : futuresPoints;

  // TradingView Lightweight Chart: create/update when chartPoints or open change
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!open || !container || !chartPoints.length) {
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        bidSeriesRef.current = null;
        askSeriesRef.current = null;
      }
      return;
    }

    // Create chart once container is visible
    if (!chartRef.current) {
      const chart = createChart(container, {
        layout: {
          background: { type: "solid", color: "#1e1e1e" },
          textColor: "#d1d4dc",
        },
        grid: {
          vertLines: { color: "#2b2b43" },
          horzLines: { color: "#363c4e" },
        },
        width: container.clientWidth,
        height: 400,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderColor: "#2b2b43",
        },
        rightPriceScale: {
          borderColor: "#2b2b43",
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        localization: {
          priceFormatter: formatPriceHuman,
        },
      });
      chartRef.current = chart;

      const bidSeries = chart.addLineSeries({
        color: "#4caf50",
        lineWidth: 2,
        title: "Bid",
      });
      const askSeries = chart.addLineSeries({
        color: "#f44336",
        lineWidth: 2,
        title: "Ask",
      });
      bidSeriesRef.current = bidSeries;
      askSeriesRef.current = askSeries;
    }

    const bidData = toLineData(chartPoints, "bid");
    const askData = toLineData(chartPoints, "ask");
    bidSeriesRef.current?.setData(bidData);
    askSeriesRef.current?.setData(askData);
    chartRef.current?.timeScale().fitContent();

    const handleResize = () => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({ width: container.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        bidSeriesRef.current = null;
        askSeriesRef.current = null;
      }
    };
  }, [open, chartPoints]);

  if (!open || !symbol) {
    return null;
  }

  let content: React.ReactNode;
  if (loading) {
    content = <Box sx={{ p: 2 }}>Loading…</Box>;
  } else if (error) {
    content = <Box sx={{ p: 2 }}>{error}</Box>;
  } else if (!chartPoints.length) {
    content = (
      <Box sx={{ p: 2 }}>
        No orderbook history. Ensure COINGLASS_API_KEY is set and the symbol is supported.
      </Box>
    );
  } else {
    const spotLine = spotSupported && spotPoints.length > 0 ? formatSummaryAskBid(spotPoints) : "Not supported";
    const futureLine = futuresPoints.length > 0 ? formatSummaryAskBid(futuresPoints) : "ask — / bid —";
    content = (
      <Box sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
          Spot: {spotLine}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          Future: {futureLine}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          Chart: {spotSupported && spotPoints.length > 0 ? "Spot" : "Futures"} aggregated orderbook (range 3%), Binance, 4h
        </Typography>
        <Box
          ref={chartContainerRef}
          sx={{ width: "100%", height: 400, minHeight: 400 }}
        />
        <Box sx={{ mt: 1, display: "flex", gap: 2 }}>
          <Typography component="span" variant="caption" sx={{ color: "#4caf50" }}>
            — Bid
          </Typography>
          <Typography component="span" variant="caption" sx={{ color: "#f44336" }}>
            — Ask
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        Order book history (4h) {symbol ? `– ${symbol}` : ""}
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent>{content}</DialogContent>
    </Dialog>
  );
};
