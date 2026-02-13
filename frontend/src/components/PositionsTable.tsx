import React, { useEffect, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import { ClosePositionDialog } from "./ClosePositionDialog";
import { FundingHistoryDialog } from "./FundingHistoryDialog";
import { OrderbookHistoryDialog } from "./OrderbookHistoryDialog";
import { OrderPlaceDialog } from "./OrderPlaceDialog";
import { useTradeIntent } from "../assistant-ui/TradeIntentContext";

export interface PositionRow {
  coin: string;
  szi: string;
  direct: string;
  leverage_type: string;
  leverage_value: string;
  entryPx: string;
  positionValue: string;
  unrealizedPnl: string;
  returnOnEquity: string;
  marginUsed: string;
  marginUsedPercentage: string;
  liquidationPx: string;
  cumFunding_allTime: string;
  lastFundingRate: string;
  markPrice: string;
  maxPositionCurLeverage?: string;
  "maxAvailablePositionOpen(USDT)"?: string;
  maxLeverage?: string;
}

interface PositionsTableProps {
  positions: PositionRow[];
  /** Refetch positions/summary (GET only). Do not use for backend refresh-positions-once. */
  onRefresh?: () => void | Promise<void>;
}

type SortKey =
  | "coin"
  | "szi"
  | "leverage_value"
  | "entryPx"
  | "positionValue"
  | "unrealizedPnl"
  | "returnOnEquity"
  | "marginUsed"
  | "marginUsedPercentage"
  | "liquidationPx"
  | "cumFunding_allTime"
  | "maxAvailablePositionOpen(USDT)";

type SortDirection = "asc" | "desc";

function pnlColor(value: string | null | undefined): "default" | "success" | "error" {
  if (!value) return "default";
  const n = Number(value);
  if (Number.isNaN(n) || n === 0) return "default";
  return n > 0 ? "success" : "error";
}

function sideColor(direct: string | null | undefined): "default" | "success" | "error" {
  if (!direct) return "default";
  const d = direct.toLowerCase();
  if (d === "long") return "success";
  if (d === "short") return "error";
  return "default";
}

function formatRoePercent(value: string | null | undefined): string {
  if (!value) return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return `${(n * 100).toFixed(2)}%`;
}

function formatDecimal2(value: string | null | undefined): string {
  if (!value) return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return n.toFixed(2);
}

function formatFundingRatePercent(value: string | null | undefined): string {
  if (!value) return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return `${(n * 100).toFixed(4)}%`;
}

function openBinanceFutures(coin: string | null | undefined) {
  if (!coin) return;
  const base = coin.toUpperCase();
  const symbol = base.endsWith("USDT") ? base : `${base}USDT`;
  const url = `https://www.binance.com/en/futures/${encodeURIComponent(symbol)}`;
  if (typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

interface LeverageDialogProps {
  open: boolean;
  coin: string;
  current: number;
  max: number;
  onClose: () => void;
  onConfirm: (leverage: number) => Promise<void> | void;
}

const PRESET_LEVERAGES = [1, 2, 5, 10];

const LeverageDialog: React.FC<LeverageDialogProps> = ({
  open,
  coin,
  current,
  max,
  onClose,
  onConfirm,
}) => {
  const [value, setValue] = useState<number>(current || 1);
  const [customInput, setCustomInput] = useState<string>("");

  useEffect(() => {
    setValue(current || 1);
    setCustomInput("");
  }, [current, open]);

  const handleSelect = (lev: number) => {
    const clamped = Math.min(Math.max(lev, 1), max || 1);
    setValue(clamped);
    setCustomInput(String(clamped));
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setCustomInput(v);
    const n = Number(v);
    if (!Number.isNaN(n)) {
      const clamped = Math.min(Math.max(Math.floor(n), 1), max || 1);
      setValue(clamped);
    }
  };

  const handleConfirm = async () => {
    await onConfirm(value);
  };

  const effectiveMax = max && max > 0 ? max : 1;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Change leverage ({coin})</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Current leverage: <strong>{current || "-" }x</strong>
        </Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          Select a preset or enter custom leverage (1–{effectiveMax}x).
        </Typography>
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, mb: 2 }}>
          {PRESET_LEVERAGES.map((lev) => (
            <Chip
              key={lev}
              label={`${lev}x`}
              size="small"
              clickable
              disabled={lev > effectiveMax}
              color={value === lev ? "primary" : "default"}
              variant={value === lev ? "filled" : "outlined"}
              onClick={() => handleSelect(lev)}
            />
          ))}
        </Box>
        <TextField
          size="small"
          fullWidth
          label={`Custom leverage (1–${effectiveMax})`}
          type="number"
          value={customInput || value}
          onChange={handleCustomChange}
          inputProps={{ min: 1, max: effectiveMax }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} size="small">
          Cancel
        </Button>
        <Button onClick={handleConfirm} size="small" variant="contained">
          Confirm
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export const PositionsTable: React.FC<PositionsTableProps> = ({ positions, onRefresh }) => {
  const tradeIntent = useTradeIntent();
  const [sortKey, setSortKey] = useState<SortKey>("unrealizedPnl");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const [enabledCurrencies, setEnabledCurrencies] = useState<Set<string> | null>(null);
  const [fundingSymbol, setFundingSymbol] = useState<string | null>(null);
  const [orderbookSymbol, setOrderbookSymbol] = useState<string | null>(null);
  const [orderbookSummaryBySymbol, setOrderbookSummaryBySymbol] = useState<Record<string, { spot: string; future: string }>>({});
  const [currencySearch, setCurrencySearch] = useState<string>("");
  const [labelFilter, setLabelFilter] = useState<string>("");
  const [labelsByCurrency, setLabelsByCurrency] = useState<Record<string, string>>({});
  const [pricePrecisionByCurrency, setPricePrecisionByCurrency] = useState<Record<string, number>>({});
  const [selectedCoins, setSelectedCoins] = useState<Set<string>>(new Set());
  const [closeDialogOpen, setCloseDialogOpen] = useState(false);
  const [orderPlaceDialogOpen, setOrderPlaceDialogOpen] = useState(false);
  const [leverageDialogState, setLeverageDialogState] = useState<{
    coin: string;
    current: number;
    max: number;
  } | null>(null);

  useEffect(() => {
    const loadLabels = async () => {
      try {
        const resp = await fetch("/api/market-data");
        const json = await resp.json();
        const rows = json.market_data ?? [];
        const byCurrency: Record<string, string> = {};
        const precByCurrency: Record<string, number> = {};
        for (const row of rows) {
          const curRaw = String(row.currency || row.symbol || "").trim().toUpperCase();
          if (!curRaw) continue;
          const base = curRaw.replace(/USDT$/, "");
          if (!base) continue;
          byCurrency[base] = String(row.labels || "");
          const precStr = String(row.pricePrecision ?? "").trim();
          const precNum = precStr !== "" ? Number(precStr) : NaN;
          if (!Number.isNaN(precNum) && precNum >= 0 && precNum <= 12) {
            precByCurrency[base] = precNum;
          }
        }
        setLabelsByCurrency(byCurrency);
        setPricePrecisionByCurrency(precByCurrency);
      } catch {
        setLabelsByCurrency({});
        setPricePrecisionByCurrency({});
      }
    };
    loadLabels();
  }, []);

  const nonZeroPositions = positions.filter((p) => {
    const size = Number(p.szi);
    return !Number.isNaN(size) && size !== 0;
  });

  const filteredByEnabled =
    enabledCurrencies === null
      ? nonZeroPositions
      : nonZeroPositions.filter((p) => enabledCurrencies.has(p.coin));

  const searchUpper = currencySearch.trim().toUpperCase();
  const labelQuery = labelFilter.trim().toLowerCase();
  let filteredPositions = filteredByEnabled;
  if (searchUpper) {
    filteredPositions = filteredPositions.filter((p) =>
      (p.coin || "").toUpperCase().startsWith(searchUpper)
    );
  }
  if (labelQuery) {
    filteredPositions = filteredPositions.filter((p) => {
      const cur = (p.coin || "").trim().toUpperCase();
      const labels = labelsByCurrency[cur] || "";
      return labels.toLowerCase().includes(labelQuery);
    });
  }

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

  const openLeverageDialog = (p: PositionRow) => {
    if (!p.coin) return;
    const currentLev = Number(p.leverage_value) || 1;
    const maxFromRow = Number(p.maxLeverage ?? "");
    const maxLev = Number.isFinite(maxFromRow) && maxFromRow >= 1 ? maxFromRow : 125;
    setLeverageDialogState({
      coin: p.coin,
      current: currentLev,
      max: maxLev,
    });
  };

  const sortedPositions = [...filteredPositions].sort((a, b) => {
    const dir = sortDir === "asc" ? 1 : -1;
    const av = a[sortKey];
    const bv = b[sortKey];

    // Try numeric compare first
    const an = Number(av);
    const bn = Number(bv);
    if (!Number.isNaN(an) && !Number.isNaN(bn)) {
      if (an < bn) return -1 * dir;
      if (an > bn) return 1 * dir;
      return 0;
    }

    // Fallback to string compare
    const as = String(av ?? "");
    const bs = String(bv ?? "");
    if (as < bs) return -1 * dir;
    if (as > bs) return 1 * dir;
    return 0;
  });

  const formatPriceForCoin = (coin: string | null | undefined, raw: string | null | undefined): string => {
    if (!raw) return "-";
    const n = Number(raw);
    if (Number.isNaN(n)) return "-";
    const cur = (coin || "").trim().toUpperCase().replace(/USDT$/, "");
    const prec = pricePrecisionByCurrency[cur];
    if (prec === undefined) return n.toString();
    return n.toFixed(prec);
  };

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
      <LeverageDialog
        open={Boolean(leverageDialogState)}
        coin={leverageDialogState?.coin || ""}
        current={leverageDialogState?.current || 1}
        max={leverageDialogState?.max || 1}
        onClose={() => setLeverageDialogState(null)}
        onConfirm={async (newLev) => {
          const state = leverageDialogState;
          if (!state) return;
          try {
            const coin = state.coin;
            const symbol = coin.toUpperCase().endsWith("USDT") ? coin.toUpperCase() : `${coin.toUpperCase()}USDT`;
            await fetch("/api/set-leverage", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ symbol, leverage: newLev }),
            });
          } catch (e) {
            // eslint-disable-next-line no-alert
            alert(`Failed to set leverage: ${e}`);
          } finally {
            setLeverageDialogState(null);
          }
        }}
      />
      <Box sx={{ mb: 2, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 2 }}>
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
          placeholder="Filter by label (e.g. DeFi, Meme)"
          sx={{ minWidth: 200 }}
        />
        <Button
          size="small"
          variant="outlined"
          onClick={() => onRefresh?.()}
        >
          Refresh
        </Button>
        <Button
          size="small"
          variant="outlined"
          disabled={selectedCoins.size === 0}
          onClick={() => {
            const list = Array.from(selectedCoins)
              .filter(Boolean)
              .map((coin) => (coin || "").toString().trim().toUpperCase());
            if (!list.length || !tradeIntent?.addTextToChat) return;
            const unique = Array.from(new Set(list));
            const msg = `Currency list: ${unique.join(", ")}\nWhat I want to do: `;
            tradeIntent.addTextToChat(msg);
          }}
        >
          Add to chat
        </Button>
        <Button
          size="small"
          variant="outlined"
          disabled={selectedCoins.size === 0}
          onClick={() => setCloseDialogOpen(true)}
        >
          Close position
        </Button>
        <Button
          size="small"
          variant="outlined"
          disabled={selectedCoins.size === 0}
          onClick={() => {
            const list = Array.from(selectedCoins).filter(Boolean);
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
          onClick={() => {
            if (typeof window !== "undefined") {
              window.dispatchEvent(new Event("cq-open-market-data"));
            }
          }}
        >
          Market data
        </Button>
      </Box>
      <OrderPlaceDialog
        open={orderPlaceDialogOpen}
        onClose={() => setOrderPlaceDialogOpen(false)}
        initialCurrencies={Array.from(selectedCoins).filter(Boolean)}
      />
      <ClosePositionDialog
        open={closeDialogOpen}
        onClose={() => setCloseDialogOpen(false)}
        positions={sortedPositions.filter(
          (p) => p.coin && selectedCoins.has(p.coin) && Number(p.szi) !== 0 && !Number.isNaN(Number(p.szi))
        )}
        onConfirm={async (options) => {
          const toClose = sortedPositions.filter(
            (p) => p.coin && selectedCoins.has(p.coin) && Number(p.szi) !== 0 && !Number.isNaN(Number(p.szi))
          );
          const symbols = toClose.map((p) =>
            p.coin.toUpperCase().endsWith("USDT") ? p.coin.toUpperCase() : `${p.coin.toUpperCase()}USDT`
          );
          if (symbols.length === 0) return;
          const body: Record<string, unknown> = {
            symbols,
            orderType: options.orderType,
          };
          if (options.orderType === "LIMIT") {
            body.useMarkPrice = options.useMarkPrice ?? true;
            if (options.limitPrice != null) body.limitPrice = options.limitPrice;
          }
          const resp = await fetch("/api/close-positions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data?.error || `Request failed (${resp.status})`);
          if (!data.success && data.error) throw new Error(data.error);
          setSelectedCoins(new Set());
        }}
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
                  indeterminate={selectedCoins.size > 0 && selectedCoins.size < sortedPositions.length}
                  checked={sortedPositions.length > 0 && selectedCoins.size === sortedPositions.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedCoins(new Set(sortedPositions.map((p) => p.coin).filter(Boolean)));
                    } else {
                      setSelectedCoins(new Set());
                    }
                  }}
                  aria-label="Select all"
                />
              </TableCell>
              <TableCell onClick={() => handleSort("coin")} sx={{ cursor: "pointer" }}>
                Currency{sortArrow("coin")}
              </TableCell>
              <TableCell align="right">
                <span
                  style={{ cursor: "pointer" }}
                  onClick={() => handleSort("entryPx")}
                >
                  Price
                  {sortArrow("entryPx")}
                </span>
                <Tooltip
                  title={
                    <>
                      <div><strong>Price levels</strong></div>
                      <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
                        Top: entry price<br />
                        Middle: current mark price<br />
                        Bottom: liquidation price
                      </div>
                    </>
                  }
                >
                  <HelpOutlineIcon
                    sx={{ fontSize: 14, ml: 0.5, verticalAlign: "middle", opacity: 0.6, cursor: "help" }}
                  />
                </Tooltip>
              </TableCell>
              <TableCell align="right">
                <span
                  style={{ cursor: "pointer" }}
                  onClick={() => handleSort("positionValue")}
                >
                  Position (USDT)
                  {sortArrow("positionValue")}
                </span>
                <Tooltip
                  title={
                    <>
                      <div><strong>Position Value (Notional)</strong></div>
                      <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
                        Position = Mark Price × Position Size
                      </div>
                    </>
                  }
                >
                  <HelpOutlineIcon
                    sx={{ fontSize: 14, ml: 0.5, verticalAlign: "middle", opacity: 0.6, cursor: "help" }}
                  />
                </Tooltip>
              </TableCell>
              <TableCell align="right">
                <span
                  style={{ cursor: "pointer" }}
                  onClick={() => handleSort("unrealizedPnl")}
                >
                  PNL
                  {sortArrow("unrealizedPnl")}
                </span>
                <Tooltip
                  title={
                    <>
                      <div>Unrealized profit and loss in USDT</div>
                      <div style={{ marginTop: 8, fontSize: 11, opacity: 0.85 }}>
                        <strong>Entry Price Formula:</strong>
                        <br />
                        Avg Entry = Total Cost / Total Qty
                        <br />
                        = (Price₁×Size₁ + Price₂×Size₂ + … + Priceₙ×Sizeₙ) / (Size₁ + Size₂ + … + Sizeₙ)
                      </div>
                    </>
                  }
                >
                  <HelpOutlineIcon
                    sx={{ fontSize: 14, ml: 0.5, verticalAlign: "middle", opacity: 0.6, cursor: "help" }}
                  />
                </Tooltip>
              </TableCell>
              <TableCell align="right">
                <span
                  style={{ cursor: "pointer" }}
                  onClick={() => handleSort("returnOnEquity")}
                >
                  ROE
                  {sortArrow("returnOnEquity")}
                </span>
                <Tooltip
                  title={
                    <>
                      <div><strong>Return on Equity (ROE)</strong></div>
                      <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
                        ROE = Unrealized PnL / Position
                        <br />
                        Measures return relative to the margin (collateral) in use.
                      </div>
                    </>
                  }
                >
                  <HelpOutlineIcon
                    sx={{ fontSize: 14, ml: 0.5, verticalAlign: "middle", opacity: 0.6, cursor: "help" }}
                  />
                </Tooltip>
              </TableCell>
              <TableCell
                align="right"
                onClick={() => handleSort("cumFunding_allTime")}
                sx={{ cursor: "pointer" }}
              >
                Funding (total){sortArrow("cumFunding_allTime")}
              </TableCell>
              <TableCell align="right">Last funding rate</TableCell>
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
            {sortedPositions.map((p) => {
              const key = p.coin || Math.random().toString(36);
              const isSelected = p.coin ? selectedCoins.has(p.coin) : false;
              return (
                <TableRow key={key} hover selected={isSelected}>
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={isSelected}
                      onChange={(e) => {
                        if (!p.coin) return;
                        setSelectedCoins((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(p.coin);
                          else next.delete(p.coin);
                          return next;
                        });
                      }}
                      aria-label={`Select ${p.coin}`}
                    />
                  </TableCell>
                  <TableCell
                    sx={{
                      cursor: "pointer",
                      py: 0.75,
                    }}
                  >
                    {(() => {
                      const base = (p.coin || "").toUpperCase();
                      const symbol = base.endsWith("USDT") ? base : `${base}USDT`;
                      const levLabel = p.leverage_value ? `${p.leverage_value}x` : "-";
                      const labelKey = base.replace(/USDT$/, "");
                      const labelText = (labelsByCurrency[labelKey] || "").trim();
                      return (
                        <Box
                          sx={{ display: "flex", flexDirection: "column", ml: 1 }}
                          onClick={() => openBinanceFutures(symbol)}
                        >
                          <Typography variant="body2" sx={{ color: "primary.main" }}>
                            {symbol}
                          </Typography>
                          <Box sx={{ display: "flex", alignItems: "center", mt: 0.4, gap: 0.5 }}>
                            <Typography
                              variant="caption"
                              sx={{
                                fontWeight: 600,
                                minWidth: 36,
                                color: sideColor(p.direct) === "success" ? "success.main" : sideColor(p.direct) === "error" ? "error.main" : "text.secondary",
                              }}
                            >
                              {(p.direct || "").toLowerCase() === "long" ? "Long" : (p.direct || "").toLowerCase() === "short" ? "Short" : p.direct || "—"}
                            </Typography>
                            <Chip
                              size="small"
                              label={levLabel}
                              variant="outlined"
                              sx={{
                                fontSize: "0.7rem",
                                height: 18,
                                borderRadius: 999,
                                px: 0.5,
                                bgcolor: "transparent",
                                borderColor: "rgba(255,255,255,0.24)",
                                color: "text.primary",
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (p.coin) openLeverageDialog(p);
                              }}
                            />
                            {labelText && (
                              <Chip
                                size="small"
                                label={labelText}
                                sx={{
                                  fontSize: "0.7rem",
                                  height: 18,
                                  borderRadius: 999,
                                  px: 0.5,
                                  bgcolor: "rgba(255,255,255,0.06)",
                                  color: "text.secondary",
                                }}
                              />
                            )}
                          </Box>
                        </Box>
                      );
                    })()}
                  </TableCell>
                  <TableCell align="right">
                    <Box sx={{ display: "flex", flexDirection: "column", fontSize: "0.75rem" }}>
                      <Box component="span" sx={{ color: "text.primary" }}>
                        {formatPriceForCoin(p.coin, p.entryPx)}
                      </Box>
                      <Box component="span" sx={{ color: "primary.main" }}>
                        {formatPriceForCoin(p.coin, p.markPrice)}
                      </Box>
                      <Box component="span" sx={{ color: "warning.main" }}>
                        {formatPriceForCoin(p.coin, p.liquidationPx)}
                      </Box>
                    </Box>
                  </TableCell>
                  <TableCell align="right">
                    {(() => {
                      const n = Number(p.positionValue);
                      if (Number.isNaN(n)) return "-";
                      return n.toFixed(2);
                    })()}
                  </TableCell>
                  <TableCell align="right">
                    <Chip
                      size="small"
                      variant="outlined"
                      color={pnlColor(p.unrealizedPnl)}
                      label={(() => {
                        if (!p.unrealizedPnl) return "-";
                        const n = Number(p.unrealizedPnl);
                        if (Number.isNaN(n)) return p.unrealizedPnl;
                        return n.toFixed(2);
                      })()}
                      sx={{ bgcolor: "transparent", border: "none" }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Chip
                      size="small"
                      variant="outlined"
                      color={pnlColor(p.returnOnEquity)}
                      label={formatRoePercent(p.returnOnEquity)}
                      sx={{ bgcolor: "transparent", border: "none" }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Chip
                      size="small"
                      variant="outlined"
                      color={pnlColor(p.cumFunding_allTime)}
                      label={p.cumFunding_allTime || "-"}
                      sx={{ bgcolor: "transparent", border: "none" }}
                    />
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ cursor: p.lastFundingRate ? "pointer" : "default", color: p.lastFundingRate ? "primary.main" : "inherit" }}
                    onClick={() => {
                      if (p.lastFundingRate) {
                        const sym = p.coin.toUpperCase().endsWith("USDT") ? p.coin.toUpperCase() : `${p.coin.toUpperCase()}USDT`;
                        setFundingSymbol(sym);
                      }
                    }}
                    >
                    {formatFundingRatePercent(p.lastFundingRate)}
                  </TableCell>
                  <TableCell align="left" sx={{ verticalAlign: "top" }}>
                    {(() => {
                      const sym = p.coin.toUpperCase().endsWith("USDT") ? p.coin.toUpperCase() : `${p.coin.toUpperCase()}USDT`;
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

