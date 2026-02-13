import React, { useMemo, useEffect, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Paper,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  Input,
  TextField,
  FormControlLabel,
} from "@mui/material";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import { FundingHistoryDialog } from "./FundingHistoryDialog";
import { OrderbookHistoryDialog } from "./OrderbookHistoryDialog";
import { OrderPlaceDialog } from "./OrderPlaceDialog";
import { useTradeIntent } from "../assistant-ui/TradeIntentContext";

/** Format price using Binance price precision (from market_data.pricePrecision). */
function formatPriceWithPrecision(value: string | undefined, precisionStr?: string): string {
  if (value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  const prec = precisionStr !== undefined && precisionStr !== "" ? Number(precisionStr) : undefined;
  if (prec !== undefined && Number.isFinite(prec) && prec >= 0 && prec <= 12) {
    return n.toFixed(prec);
  }
  // Fallback: strip trailing zeros by using JS default string form.
  return n.toString();
}

/** Format large USDT numbers as human-readable (e.g. 52.2B, 375M, 1.2K). */
function formatHumanUsdt(value: string | undefined): string {
  if (value === undefined || value === "") return "-";
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return value;
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return n.toFixed(2);
}

/** Format percentage with sign and color. Optional: compute % from absolute priceChange and markPrice if percent not provided. */
function formatPercent(
  percentValue: string | undefined,
  fallbackPriceChange?: string,
  fallbackMarkPrice?: string
): { text: string; color: "success.main" | "error.main" | "text.primary" } {
  if (percentValue !== undefined && percentValue !== "") {
    const n = parseFloat(percentValue);
    if (Number.isFinite(n)) {
      const text = `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
      const color = n > 0 ? "success.main" : n < 0 ? "error.main" : "text.primary";
      return { text, color };
    }
  }
  // Fallback: compute % from priceChange and markPrice (e.g. when CSV was written before priceChange24h% column existed)
  if (fallbackPriceChange !== undefined && fallbackMarkPrice !== undefined) {
    const change = parseFloat(fallbackPriceChange);
    const mark = parseFloat(fallbackMarkPrice);
    if (Number.isFinite(change) && Number.isFinite(mark) && mark !== change) {
      const pct = (change / (mark - change)) * 100;
      const text = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
      const color = pct > 0 ? "success.main" : pct < 0 ? "error.main" : "text.primary";
      return { text, color };
    }
  }
  return { text: "-", color: "text.primary" };
}

function openBinanceFuturesByCurrency(currency: string | null | undefined) {
  if (!currency) return;
  const base = currency.toUpperCase();
  const symbol = base.endsWith("USDT") ? base : `${base}USDT`;
  const url = `https://www.binance.com/en/futures/${encodeURIComponent(symbol)}`;
  if (typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

export interface MarketDataRow {
  currency: string;
  maxLeverage: string;
  markPrice: string;
  pricePrecision?: string;
  lastFundingRate: string;
  lastFundingTime: string;
  fundingTimesPerDay?: string;
  todayFundRate?: string;
  avgDayFundRate72h?: string;
  "volume24h(USDT)": string;
  "priceChange24h(USDT)": string;
  "priceChange24h%(USDT)"?: string;
  "openInterest(USDT)": string;
  lastUpdateTime: string;
  spotEnabled?: string;
  labels: string;
}

type SortKey = "volume24h" | "priceChange24hPct";
type SortDirection = "asc" | "desc";

/** Numeric value for sorting (raw USDT or computed %). */
function getSortNumVolume(r: MarketDataRow): number {
  const v = r["volume24h(USDT)"];
  if (v === undefined || v === "") return -Infinity;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : -Infinity;
}

function getSortNumPriceChgPct(r: MarketDataRow): number {
  const pct = r["priceChange24h%(USDT)"];
  if (pct !== undefined && pct !== "") {
    const n = parseFloat(pct);
    if (Number.isFinite(n)) return n;
  }
  const change = parseFloat(r["priceChange24h(USDT)"] ?? "");
  const mark = parseFloat(r.markPrice ?? "");
  if (Number.isFinite(change) && Number.isFinite(mark) && mark !== change) {
    return (change / (mark - change)) * 100;
  }
  return -Infinity;
}

export const MarketDataTable: React.FC = () => {
  const tradeIntent = useTradeIntent();
  const [rows, setRows] = useState<MarketDataRow[]>([]);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const [editingCurrency, setEditingCurrency] = useState<string | null>(null);
  const [editingLabels, setEditingLabels] = useState<string>("");
  const [labelFilter, setLabelFilter] = useState<string>("");
  const [currencySearch, setCurrencySearch] = useState<string>("");
  const [openInterestMinUsdt, setOpenInterestMinUsdt] = useState<string>("");
  const [volume24hMinUsdt, setVolume24hMinUsdt] = useState<string>("");
  const [fundingSymbol, setFundingSymbol] = useState<string | null>(null);
  const [orderbookSymbol, setOrderbookSymbol] = useState<string | null>(null);
  const [orderbookSummaryBySymbol, setOrderbookSummaryBySymbol] = useState<Record<string, { spot: string; future: string }>>({});
  const [selectedCurrencies, setSelectedCurrencies] = useState<Set<string>>(new Set());
  const [orderPlaceDialogOpen, setOrderPlaceDialogOpen] = useState(false);
  const [hideWithPositions, setHideWithPositions] = useState<boolean>(true);
  const [coinsWithPositions, setCoinsWithPositions] = useState<Set<string>>(new Set());

  const formatFundingRatePercent = (value: string | null | undefined): string => {
    if (!value) return "-";
    const n = Number(value);
    if (Number.isNaN(n)) return "-";
    return `${(n * 100).toFixed(4)}%`;
  };

  const formatDayFundingPercent = (value: string | null | undefined): string => {
    if (!value) return "-";
    const n = Number(value);
    if (Number.isNaN(n)) return "-";
    return `${(n * 100).toFixed(3)}%`;
  };

  const load = async () => {
    try {
      const resp = await fetch("/api/market-data");
      const json = await resp.json();
      setRows(json.market_data ?? []);
    } catch (e) {
      console.error("Failed to load market data", e);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const loadPositions = async () => {
      try {
        const resp = await fetch("/api/positions");
        const json = await resp.json();
        const positions: Array<{ coin?: string; szi?: string }> = json.positions || [];
        const withPos = new Set<string>();
        for (const p of positions) {
          const coin = (p.coin || "").trim().toUpperCase();
          const size = Number(p.szi);
          if (!coin || Number.isNaN(size) || size === 0) continue;
          withPos.add(coin);
        }
        setCoinsWithPositions(withPos);
      } catch {
        setCoinsWithPositions(new Set());
      }
    };
    loadPositions();
  }, []);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortArrow = (key: SortKey) => {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  const saveLabels = async (currency: string, labels: string) => {
    try {
      const resp = await fetch("/api/market-data/labels", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currency, labels }),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        console.error("Failed to save labels", j);
        return;
      }
      setRows((prev) =>
        prev.map((r) =>
          r.currency === currency ? { ...r, labels } : r
        )
      );
    } catch (e) {
      console.error("Failed to save labels", e);
    } finally {
      setEditingCurrency(null);
      setEditingLabels("");
    }
  };

  const handleLabelsBlur = (currency: string) => {
    if (editingCurrency !== currency) return;
    saveLabels(currency, editingLabels);
  };

      const handleLabelsKeyDown = (
      e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
      currency: string
    ) => {
    if (e.key === "Enter") {
      e.currentTarget.blur();
    }
  };

  const filteredRows = useMemo(() => {
    let result = rows;
    const searchUpper = currencySearch.trim().toUpperCase();
    if (searchUpper) {
      result = result.filter((r) => (r.currency || "").toUpperCase().startsWith(searchUpper));
    }
    const q = labelFilter.trim().toLowerCase();
    if (q) {
      result = result.filter((r) => (r.labels ?? "").toLowerCase().includes(q));
    }
    const minOi = openInterestMinUsdt.trim();
    if (minOi) {
      const threshold = parseFloat(minOi);
      if (Number.isFinite(threshold)) {
        result = result.filter((r) => {
          const v = parseFloat(r["openInterest(USDT)"] ?? "");
          return Number.isFinite(v) && v >= threshold;
        });
      }
    }
    const minVol = volume24hMinUsdt.trim();
    if (minVol) {
      const threshold = parseFloat(minVol);
      if (Number.isFinite(threshold)) {
        result = result.filter((r) => {
          const v = parseFloat(r["volume24h(USDT)"] ?? "");
          return Number.isFinite(v) && v >= threshold;
        });
      }
    }
    if (hideWithPositions && coinsWithPositions.size > 0) {
      result = result.filter((r) => {
        const base = (r.currency || "").trim().toUpperCase().replace(/USDT$/, "");
        if (!base) return true;
        return !coinsWithPositions.has(base);
      });
    }
    return result;
  }, [rows, currencySearch, labelFilter, openInterestMinUsdt, volume24hMinUsdt, hideWithPositions, coinsWithPositions]);

  const sortedRows = useMemo(() => {
    if (!sortKey) return filteredRows;
    const getNum = sortKey === "volume24h" ? getSortNumVolume : getSortNumPriceChgPct;
    return [...filteredRows].sort((a, b) => {
      const va = getNum(a);
      const vb = getNum(b);
      if (va !== vb) return sortDir === "asc" ? (va > vb ? 1 : -1) : va < vb ? 1 : -1;
      return (a.currency || "").localeCompare(b.currency || "");
    });
  }, [filteredRows, sortKey, sortDir]);

  return (
    <Box>
      <FundingHistoryDialog
        symbol={fundingSymbol}
        open={Boolean(fundingSymbol)}
        onClose={() => setFundingSymbol(null)}
      />
      <OrderbookHistoryDialog
        symbol={orderbookSymbol}
        open={Boolean(orderbookSymbol)}
        onClose={() => setOrderbookSymbol(null)}
        onSummaryLoaded={(sym, spot, future) =>
          setOrderbookSummaryBySymbol((prev) => ({ ...prev, [sym]: { spot, future } }))
        }
      />
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, alignItems: "center" }}>
            <TextField
              size="small"
              label="Currency"
              value={currencySearch}
              onChange={(e) => setCurrencySearch(e.target.value)}
              placeholder="Search by currency (starts with)"
              sx={{ minWidth: 200 }}
              inputProps={{ "aria-label": "Currency search" }}
            />
            <TextField
              size="small"
              label="Label"
              value={labelFilter}
              onChange={(e) => setLabelFilter(e.target.value)}
              placeholder="Filter by label"
              sx={{ minWidth: 200 }}
              inputProps={{ "aria-label": "Filter by label" }}
            />
            <TextField
              size="small"
              label="Open interest min (USDT)"
              value={openInterestMinUsdt}
              onChange={(e) => setOpenInterestMinUsdt(e.target.value)}
              placeholder="e.g. 1000000"
              type="number"
              inputProps={{ min: 0, step: 100000, "aria-label": "Min open interest in USDT" }}
              sx={{ minWidth: 200 }}
            />
            <TextField
              size="small"
              label="Volume 24h min (USDT)"
              value={volume24hMinUsdt}
              onChange={(e) => setVolume24hMinUsdt(e.target.value)}
              placeholder="e.g. 1000000"
              type="number"
              inputProps={{ min: 0, step: 100000, "aria-label": "Min 24h volume in USDT" }}
              sx={{ minWidth: 200 }}
            />
            <Button
              size="small"
              variant="outlined"
              disabled={selectedCurrencies.size === 0}
              onClick={() => {
                const list = Array.from(selectedCurrencies).filter(Boolean);
                if (list.length && tradeIntent?.openChatWithTrade) {
                  tradeIntent.openChatWithTrade(list);
                }
              }}
              sx={{ display: "none" }}
            >
              Trade
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={load}
            >
              Refresh
            </Button>
            <Button
              size="small"
              variant="outlined"
              disabled={selectedCurrencies.size === 0}
              onClick={() => {
                const list = Array.from(selectedCurrencies)
                  .filter(Boolean)
                  .map((cur) => (cur || "").toString().trim().toUpperCase());
                if (!list.length || !tradeIntent?.addTextToChat) return;
                const unique = Array.from(new Set(list));
                const msg = `Currency list: ${unique.join(", ")}\nWhat I want to do: `;
                tradeIntent.addTextToChat(msg);
              }}
            >
              Add to chat
            </Button>
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={hideWithPositions}
                  onChange={(e) => setHideWithPositions(e.target.checked)}
                />
              }
              label="Hide symbols with open positions"
              sx={{ ml: 2 }}
            />
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              if (typeof window !== "undefined") {
                window.dispatchEvent(new Event("cq-open-positions"));
              }
            }}
          >
            Positions
          </Button>
        </Box>
      </Box>
      <OrderPlaceDialog
        open={orderPlaceDialogOpen}
        onClose={() => setOrderPlaceDialogOpen(false)}
        initialCurrencies={Array.from(selectedCurrencies).filter(Boolean)}
      />
      <TableContainer
        component={Paper}
        sx={{
          maxHeight: "80vh",
          scrollbarWidth: "none",
          msOverflowStyle: "none",
          "&::-webkit-scrollbar": { display: "none" },
        }}
      >
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={selectedCurrencies.size > 0 && selectedCurrencies.size < sortedRows.length}
                  checked={sortedRows.length > 0 && selectedCurrencies.size === sortedRows.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedCurrencies(new Set(sortedRows.map((r) => r.currency).filter(Boolean)));
                    } else {
                      setSelectedCurrencies(new Set());
                    }
                  }}
                  aria-label="Select all"
                />
              </TableCell>
              <TableCell>Currency</TableCell>
              <TableCell align="right">Max lev</TableCell>
              <TableCell align="right">Mark price</TableCell>
              <TableCell align="right">Last funding rate</TableCell>
              <TableCell align="right">Fund times/day</TableCell>
              <TableCell align="right">
                <Tooltip title="Last funding rate × Fund times/day">
                  <span style={{ cursor: "help" }}>Today fund rate ?</span>
                </Tooltip>
              </TableCell>
              <TableCell align="right">
                <Tooltip title="Average of 72 hours × Fund times/day">
                  <span style={{ cursor: "help" }}>Avg day fund 72h ?</span>
                </Tooltip>
              </TableCell>
              <TableCell
                align="right"
                onClick={() => handleSort("volume24h")}
                sx={{ cursor: "pointer" }}
              >
                Volume 24h (USDT){sortArrow("volume24h")}
              </TableCell>
              <TableCell
                align="right"
                onClick={() => handleSort("priceChange24hPct")}
                sx={{ cursor: "pointer" }}
              >
                Price chg 24h % (USDT){sortArrow("priceChange24hPct")}
              </TableCell>
              <TableCell align="right">Open interest (USDT)</TableCell>
              <TableCell align="center">
                <Tooltip title="Symbol enabled for SPOT trading on Binance">
                  <span style={{ cursor: "help" }}>SPOT</span>
                </Tooltip>
              </TableCell>
              <TableCell>Labels</TableCell>
              <TableCell align="center">
                <Tooltip
                  title={
                    <>
                      Spot: ask volume / bid volume. Future: ask volume / bid volume. If spot is not supported for this symbol, it shows Not supported.
                    </>
                  }
                >
                  <span style={{ cursor: "help", display: "inline-flex", alignItems: "center", gap: 4 }}>
                    Order book history (4h)
                    <HelpOutlineIcon sx={{ fontSize: 14, opacity: 0.7 }} />
                  </span>
                </Tooltip>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedRows.map((r) => {
              const pct = formatPercent(
                r["priceChange24h%(USDT)"],
                r["priceChange24h(USDT)"],
                r.markPrice
              );
              const isSelected = selectedCurrencies.has(r.currency);
              return (
                <TableRow key={r.currency} hover selected={isSelected}>
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={isSelected}
                      onChange={(e) => {
                        setSelectedCurrencies((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(r.currency);
                          else next.delete(r.currency);
                          return next;
                        });
                      }}
                      aria-label={`Select ${r.currency}`}
                    />
                  </TableCell>
                  <TableCell
                    sx={{ cursor: "pointer", color: "primary.main" }}
                    onClick={() => openBinanceFuturesByCurrency(r.currency)}
                  >
                    {r.currency}
                  </TableCell>
                  <TableCell align="right">{r.maxLeverage || "-"}</TableCell>
                  <TableCell align="right">
                    {formatPriceWithPrecision(r.markPrice, r.pricePrecision)}
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ cursor: r.lastFundingRate ? "pointer" : "default", color: r.lastFundingRate ? "primary.main" : "inherit" }}
                    onClick={() => {
                      if (r.lastFundingRate) {
                        const sym = r.currency.toUpperCase().endsWith("USDT")
                          ? r.currency.toUpperCase()
                          : `${r.currency.toUpperCase()}USDT`;
                        setFundingSymbol(sym);
                      }
                    }}
                  >
                    {formatFundingRatePercent(r.lastFundingRate)}
                  </TableCell>
                  <TableCell align="right">{r.fundingTimesPerDay ?? "-"}</TableCell>
                  <TableCell align="right">{formatDayFundingPercent(r.todayFundRate)}</TableCell>
                  <TableCell align="right">{formatDayFundingPercent(r.avgDayFundRate72h)}</TableCell>
                  <TableCell align="right">{formatHumanUsdt(r["volume24h(USDT)"])}</TableCell>
                  <TableCell align="right" sx={{ color: pct.color, fontWeight: 500 }}>
                    {pct.text}
                  </TableCell>
                  <TableCell align="right">{formatHumanUsdt(r["openInterest(USDT)"])}</TableCell>
                  <TableCell align="center">
                    {(r.spotEnabled || "").toLowerCase() === "true" ? "Yes" : "No"}
                  </TableCell>
                  <TableCell
                    onClick={() => {
                      setEditingCurrency(r.currency);
                      setEditingLabels(r.labels || "");
                    }}
                    sx={{
                      cursor: "pointer",
                      minWidth: 120,
                      "&:hover": { bgcolor: "action.hover" },
                    }}
                  >
                    {editingCurrency === r.currency ? (
                      <Box onClick={(e) => e.stopPropagation()}>
                        <Input
                          value={editingLabels}
                          onChange={(e) => setEditingLabels(e.target.value)}
                          onBlur={() => handleLabelsBlur(r.currency)}
                          onKeyDown={(e) => handleLabelsKeyDown(e, r.currency)}
                          size="small"
                          fullWidth
                          disableUnderline
                          sx={{ fontSize: "inherit" }}
                          autoFocus
                          inputProps={{ "aria-label": `Edit labels for ${r.currency}` }}
                        />
                      </Box>
                    ) : (
                      (r.labels || "-")
                    )}
                  </TableCell>
                  <TableCell align="left" sx={{ verticalAlign: "top" }}>
                    {(() => {
                      const sym = r.currency.toUpperCase().endsWith("USDT")
                        ? r.currency.toUpperCase()
                        : `${r.currency.toUpperCase()}USDT`;
                      const summary = orderbookSummaryBySymbol[sym];
                      const openView = () => setOrderbookSymbol(sym);
                      return (
                        <>
                          <Box sx={{ fontSize: "0.8125rem", color: "text.secondary" }}>
                            <Box component="span">Spot: {summary?.spot ?? "ask — / bid —"}</Box>
                            <Typography
                              component="span"
                              variant="body2"
                              sx={{ color: "primary.main", cursor: "pointer", ml: 0.5, "&:hover": { textDecoration: "underline" } }}
                              onClick={openView}
                            >
                              View
                            </Typography>
                          </Box>
                          <Box sx={{ fontSize: "0.8125rem", color: "text.secondary" }}>
                            <Box component="span">Future: {summary?.future ?? "ask — / bid —"}</Box>
                            <Typography
                              component="span"
                              variant="body2"
                              sx={{ color: "primary.main", cursor: "pointer", ml: 0.5, "&:hover": { textDecoration: "underline" } }}
                              onClick={openView}
                            >
                              View
                            </Typography>
                          </Box>
                        </>
                      );
                    })()}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};
