import React, { useEffect, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

export interface OrderRowForm {
  currency: string;
  orderType: "MARKET" | "LIMIT";
  limitPrice: string;
  amountUsdt: string;
  positionSide: "LONG" | "SHORT";
}

export interface PreviewRow {
  symbol: string;
  currency: string;
  currentSize: number;
  currentSide: string;
  newSize: number;
  newSide: string;
  orderQty: number;
  orderSide: string;
  markPrice: number;
}

interface OrderPlaceDialogProps {
  open: boolean;
  onClose: () => void;
  /** Prefill currency list (e.g. from selected positions or market rows). */
  initialCurrencies: string[];
  onSuccess?: () => void;
}

function toSymbol(currency: string): string {
  const c = (currency || "").trim().toUpperCase();
  return c.endsWith("USDT") ? c : c + "USDT";
}

export const OrderPlaceDialog: React.FC<OrderPlaceDialogProps> = ({
  open,
  onClose,
  initialCurrencies,
  onSuccess,
}) => {
  const [step, setStep] = useState<"form" | "preview" | "placing" | "done">("form");
  const [leverage, setLeverage] = useState<number>(10);
  const [rows, setRows] = useState<OrderRowForm[]>([]);
  const [markPrices, setMarkPrices] = useState<Record<string, number>>({});
  const [previewData, setPreviewData] = useState<PreviewRow[]>([]);
  const [placingResult, setPlacingResult] = useState<{ ok: boolean; responses: unknown[]; error?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composePrompt, setComposePrompt] = useState<string>("");
  const [composeReply, setComposeReply] = useState<string | null>(null);
  const [composeLoading, setComposeLoading] = useState<boolean>(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composeSuggestions, setComposeSuggestions] = useState<
    {
      currency: string;
      amountUsdt: number;
      positionSide: "LONG" | "SHORT";
      orderType: "MARKET" | "LIMIT";
      limitPrice?: number | null;
    }[]
  >([]);

  useEffect(() => {
    if (!open) return;
    setStep("form");
    setPlacingResult(null);
    setError(null);
    setComposePrompt("");
    setComposeReply(null);
    setComposeError(null);
    setComposeSuggestions([]);
    const list = initialCurrencies.length > 0 ? initialCurrencies : [""];
    setRows(
      list.map((c) => ({
        currency: (c || "").trim().toUpperCase().replace(/USDT$/, "") || "",
        orderType: "MARKET" as const,
        limitPrice: "",
        amountUsdt: "",
        positionSide: "LONG" as const,
      }))
    );
  }, [open, initialCurrencies]);

  const currencyList = rows.map((r) => r.currency).join(",");
  useEffect(() => {
    if (!open || rows.length === 0) return;
    const symbols = rows.map((r) => toSymbol(r.currency)).filter(Boolean);
    if (symbols.length === 0) return;
    fetch(`/api/mark-prices?symbols=${symbols.join(",")}`)
      .then((res) => res.json())
      .then((data) => setMarkPrices(data.markPrices || {}))
      .catch(() => setMarkPrices({}));
  }, [open, currencyList]);

  const updateRow = (index: number, patch: Partial<OrderRowForm>) => {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  };

  const addRow = () => {
    setRows((prev) => [...prev, { currency: "", orderType: "MARKET", limitPrice: "", amountUsdt: "", positionSide: "LONG" }]);
  };

  const removeRow = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
  };

  const validRows = rows.filter((r) => r.currency.trim() && Number(r.amountUsdt) > 0);

  const handleApplySuggestion = (suggestion: {
    currency: string;
    amountUsdt: number;
    positionSide: "LONG" | "SHORT";
    orderType: "MARKET" | "LIMIT";
    limitPrice?: number | null;
  }) => {
    setRows((prev) => {
      const targetIndex = prev.findIndex((r) => !r.currency.trim());
      const baseRow: OrderRowForm = {
        currency: suggestion.currency.replace(/USDT$/, ""),
        orderType: suggestion.orderType,
        limitPrice: suggestion.limitPrice != null ? String(suggestion.limitPrice) : "",
        amountUsdt: suggestion.amountUsdt ? String(suggestion.amountUsdt) : "",
        positionSide: suggestion.positionSide,
      };
      if (targetIndex === -1) {
        return [...prev, baseRow];
      }
      const next = [...prev];
      next[targetIndex] = { ...next[targetIndex], ...baseRow };
      return next;
    });
  };

  const handleApplyAllSuggestions = () => {
    if (composeSuggestions.length === 0) return;
    setRows((prev) => {
      const byCurrency: Record<string, typeof composeSuggestions[number]> = {};
      for (const s of composeSuggestions) {
        const key = s.currency.replace(/USDT$/, "");
        byCurrency[key] = s;
      }
      const updated = [...prev];
      const existingCurrencies = new Set(
        updated.map((r) => r.currency.trim()).filter(Boolean)
      );
      // Update existing rows for matching currencies
      for (let i = 0; i < updated.length; i++) {
        const cur = updated[i].currency.trim();
        if (!cur) continue;
        const s = byCurrency[cur];
        if (!s) continue;
        updated[i] = {
          ...updated[i],
          currency: cur,
          orderType: s.orderType,
          limitPrice: s.limitPrice != null ? String(s.limitPrice) : "",
          amountUsdt: s.amountUsdt ? String(s.amountUsdt) : "",
          positionSide: s.positionSide,
        };
      }
      // Append new rows for currencies not already in the table
      for (const [cur, s] of Object.entries(byCurrency)) {
        if (existingCurrencies.has(cur)) continue;
        updated.push({
          currency: cur,
          orderType: s.orderType,
          limitPrice: s.limitPrice != null ? String(s.limitPrice) : "",
          amountUsdt: s.amountUsdt ? String(s.amountUsdt) : "",
          positionSide: s.positionSide,
        });
      }
      return updated;
    });
  };

  const handleCompose = async () => {
    const trimmedPrompt = composePrompt.trim();
    const nonEmptyRows = rows.filter((r) => r.currency.trim());
    if (!trimmedPrompt && nonEmptyRows.length === 0) {
      setComposeError("Add at least one row with a currency or enter a prompt.");
      return;
    }
    setComposeError(null);
    setComposeLoading(true);
    try {
      const body = {
        prompt: trimmedPrompt,
        symbols: nonEmptyRows.map((r) => toSymbol(r.currency)),
      };
      const res = await fetch("/api/compose-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setComposeError(data?.error || `HTTP ${res.status}`);
        setComposeReply(null);
        setComposeSuggestions([]);
      } else {
        setComposeReply(data.reply || null);
        setComposeSuggestions(Array.isArray(data.orders) ? data.orders : []);
      }
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : "Failed to compose orders.");
      setComposeReply(null);
      setComposeSuggestions([]);
    } finally {
      setComposeLoading(false);
    }
  };

  const handleConfirmForm = async () => {
    if (validRows.length === 0) {
      setError("Add at least one order with currency and amount (USDT) > 0.");
      return;
    }
    setError(null);
    try {
      const posRes = await fetch("/api/positions");
      const posJson = await posRes.json();
      const positions: Array<{ coin?: string; szi?: string; direct?: string }> = posJson.positions || [];
      const bySymbol: Record<string, { size: number; side: string }> = {};
      for (const p of positions) {
        const coin = (p.coin || "").trim();
        if (!coin) continue;
        const symbol = toSymbol(coin);
        const szi = Number(p.szi) || 0;
        const direct = (p.direct || "").trim();
        const side = direct.toLowerCase() === "short" ? "Short" : "Long";
        const signed = direct.toLowerCase() === "short" ? -szi : szi;
        bySymbol[symbol] = { size: Math.abs(signed), side };
      }
      const orderDeltaBySymbol: Record<string, { qty: number; orders: Array<{ qty: number; side: string }> }> = {};
      for (const r of validRows) {
        const symbol = toSymbol(r.currency);
        const mark = markPrices[symbol] ?? 0;
        const amount = Number(r.amountUsdt) || 0;
        const qty = mark > 0 ? amount / mark : 0;
        const orderSide = r.positionSide;
        const signedQty = orderSide === "SHORT" ? -qty : qty;
        if (!orderDeltaBySymbol[symbol]) orderDeltaBySymbol[symbol] = { qty: 0, orders: [] };
        orderDeltaBySymbol[symbol].qty += signedQty;
        orderDeltaBySymbol[symbol].orders.push({ qty, side: orderSide });
      }
      const preview: PreviewRow[] = [];
      for (const [symbol, delta] of Object.entries(orderDeltaBySymbol)) {
        const currency = symbol.replace(/USDT$/, "");
        const current = bySymbol[symbol] ?? { size: 0, side: "—" };
        const currentSigned = current.side === "Short" ? -current.size : current.size;
        const newSigned = currentSigned + delta.qty;
        const newSize = Math.abs(newSigned);
        const newSide = newSigned >= 0 ? "Long" : "Short";
        const orderQty = delta.orders.reduce((s, o) => s + o.qty, 0);
        const orderSide = delta.qty >= 0 ? "LONG" : "SHORT";
        preview.push({
          symbol,
          currency,
          currentSize: current.size,
          currentSide: current.side,
          newSize,
          newSide,
          orderQty,
          orderSide,
          markPrice: markPrices[symbol] ?? 0,
        });
      }
      setPreviewData(preview);
      setStep("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions for preview.");
    }
  };

  const handlePlaceOrders = async () => {
    setError(null);
    setStep("placing");
    try {
      const body = {
        leverage: leverage,
        orders: validRows.map((r) => {
          const sym = toSymbol(r.currency);
          const payload: Record<string, unknown> = {
            symbol: sym,
            type: r.orderType,
            amountUsdt: Number(r.amountUsdt),
            positionSide: r.positionSide,
          };
          if (r.orderType === "LIMIT" && r.limitPrice.trim()) {
            payload.price = Number(r.limitPrice);
          }
          return payload;
        }),
      };
      const res = await fetch("/api/place-batch-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setPlacingResult({ ok: false, responses: [], error: data?.error || `HTTP ${res.status}` });
      } else {
        setPlacingResult({ ok: data.ok, responses: data.responses || [], error: data.error });
        if (data.ok) onSuccess?.();
      }
      setStep("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed.");
      setStep("preview");
    }
  };

  const handleBack = () => {
    setStep("form");
    setPreviewData([]);
    setError(null);
  };

  const handleClose = () => {
    setStep("form");
    setPreviewData([]);
    setPlacingResult(null);
    setError(null);
    onClose();
  };

  if (!open) return null;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        Place orders
        <IconButton size="small" onClick={handleClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {step === "form" && (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Add one or more orders. Limit orders default to mark price if left empty (fetch on open).
            </Typography>
            <Box sx={{ mb: 2, display: "flex", alignItems: "center", gap: 2 }}>
              <TextField
                size="small"
                type="number"
                label="Leverage"
                value={leverage}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!Number.isNaN(v) && v >= 1 && v <= 125) setLeverage(v);
                }}
                inputProps={{ min: 1, max: 125, step: 1, "aria-label": "Leverage" }}
                sx={{ width: 100 }}
              />
              <Typography variant="caption" color="text.secondary">
                Applied to all symbols before placing (Binance min notional 100 USDT).
              </Typography>
            </Box>
            <TableContainer sx={{ maxHeight: 360 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Currency</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Limit price</TableCell>
                    <TableCell>Amount (USDT)</TableCell>
                    <TableCell>Side</TableCell>
                    <TableCell padding="none" width={48} />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <TextField
                          size="small"
                          placeholder="e.g. BTC"
                          value={r.currency}
                          onChange={(e) => updateRow(i, { currency: e.target.value.toUpperCase().replace(/USDT$/, "") })}
                          inputProps={{ "aria-label": "Currency" }}
                          sx={{ minWidth: 100 }}
                        />
                      </TableCell>
                      <TableCell>
                        <FormControl size="small" sx={{ minWidth: 100 }}>
                          <Select
                            value={r.orderType}
                            onChange={(e) => updateRow(i, { orderType: e.target.value as "MARKET" | "LIMIT" })}
                            aria-label="Order type"
                          >
                            <MenuItem value="MARKET">Market</MenuItem>
                            <MenuItem value="LIMIT">Limit</MenuItem>
                          </Select>
                        </FormControl>
                      </TableCell>
                      <TableCell>
                        <TextField
                          size="small"
                          type="number"
                          placeholder={
                            r.orderType === "LIMIT"
                              ? markPrices[toSymbol(r.currency)]?.toString() ?? "Mark"
                              : "—"
                          }
                          value={r.limitPrice}
                          disabled={r.orderType === "MARKET"}
                          onChange={(e) => updateRow(i, { limitPrice: e.target.value })}
                          inputProps={{ step: "any", min: 0, "aria-label": "Limit price" }}
                          sx={{ minWidth: 100 }}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          size="small"
                          type="number"
                          required
                          placeholder="0"
                          value={r.amountUsdt}
                          onChange={(e) => updateRow(i, { amountUsdt: e.target.value })}
                          inputProps={{ step: "any", min: 0, "aria-label": "Amount USDT" }}
                          sx={{ minWidth: 100 }}
                        />
                      </TableCell>
                      <TableCell>
                        <FormControl size="small" sx={{ minWidth: 90 }}>
                          <Select
                            value={r.positionSide}
                            onChange={(e) => updateRow(i, { positionSide: e.target.value as "LONG" | "SHORT" })}
                            aria-label="Position side"
                          >
                            <MenuItem value="LONG">LONG</MenuItem>
                            <MenuItem value="SHORT">SHORT</MenuItem>
                          </Select>
                        </FormControl>
                      </TableCell>
                      <TableCell padding="none">
                        <IconButton size="small" onClick={() => removeRow(i)} aria-label="Remove row">
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            <Button startIcon={<AddIcon />} size="small" onClick={addRow} sx={{ mt: 1 }}>
              Add row
            </Button>

            <Box sx={{ mt: 3, p: 2, borderRadius: 1, border: "1px solid", borderColor: "divider" }}>
              <TextField
                multiline
                minRows={2}
                maxRows={6}
                fullWidth
                size="small"
                placeholder="Ask AI to compose batch orders…"
                value={composePrompt}
                onChange={(e) => setComposePrompt(e.target.value)}
                sx={{ mb: 1.5 }}
              />
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, mb: 1.5 }}>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() =>
                    setComposePrompt("long btc, short altcoins with total amount: 1000usdt")
                  }
                  sx={{
                    borderRadius: 999,
                    borderColor: "transparent",
                    bgcolor: "background.paper",
                    textTransform: "none",
                    px: 2,
                    py: 0.5,
                  }}
                >
                  long btc, short altcoins with total amount: 1000usdt
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setComposePrompt("increase positions to 1.2x")}
                  sx={{
                    borderRadius: 999,
                    borderColor: "transparent",
                    bgcolor: "background.paper",
                    textTransform: "none",
                    px: 2,
                    py: 0.5,
                  }}
                >
                  increase positions to 1.2x
                </Button>
              </Box>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mb: 1 }}>
                <Button
                  variant="contained"
                  size="small"
                  onClick={handleCompose}
                  disabled={composeLoading}
                >
                  {composeLoading ? "Composing..." : "Compose"}
                </Button>
                {composeError && (
                  <Typography variant="body2" color="error">
                    {composeError}
                  </Typography>
                )}
              </Box>
              {composeReply && (
                <Typography
                  variant="body2"
                  component="pre"
                  sx={{
                    mt: 1,
                    mb: 1,
                    p: 1,
                    borderRadius: 1,
                    bgcolor: "background.default",
                    maxHeight: 160,
                    overflow: "auto",
                    fontSize: "0.75rem",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {composeReply}
                </Typography>
              )}
              {composeSuggestions.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 0.5 }}>
                    <Typography variant="subtitle2">Suggested orders</Typography>
                    <Button size="small" onClick={handleApplyAllSuggestions}>
                      Select ALL
                    </Button>
                  </Box>
                  <TableContainer sx={{ maxHeight: 200 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>Currency</TableCell>
                          <TableCell align="right">Amount (USDT)</TableCell>
                          <TableCell>Side</TableCell>
                          <TableCell>Type</TableCell>
                          <TableCell padding="none" />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {composeSuggestions.map((s, idx) => (
                          <TableRow key={idx}>
                            <TableCell>{s.currency}</TableCell>
                            <TableCell align="right">{s.amountUsdt.toFixed(2)}</TableCell>
                            <TableCell>{s.positionSide}</TableCell>
                            <TableCell>{s.orderType}</TableCell>
                            <TableCell padding="none">
                              <Button
                                size="small"
                                onClick={() => handleApplySuggestion(s)}
                              >
                                Select
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}
            </Box>
          </>
        )}

        {step === "preview" && (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Preview: current position vs new position after orders.
            </Typography>
            <TableContainer sx={{ maxHeight: 360 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Symbol</TableCell>
                    <TableCell align="right">Current size</TableCell>
                    <TableCell>Current side</TableCell>
                    <TableCell align="right">Order (qty)</TableCell>
                    <TableCell>Order side</TableCell>
                    <TableCell align="right">New size</TableCell>
                    <TableCell>New side</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {previewData.map((p) => (
                    <TableRow key={p.symbol}>
                      <TableCell>{p.symbol}</TableCell>
                      <TableCell align="right">{p.currentSize.toFixed(4)}</TableCell>
                      <TableCell>{p.currentSide}</TableCell>
                      <TableCell align="right">{p.orderQty.toFixed(4)}</TableCell>
                      <TableCell>{p.orderSide}</TableCell>
                      <TableCell align="right">{p.newSize.toFixed(4)}</TableCell>
                      <TableCell>{p.newSide}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}

        {step === "placing" && (
          <Typography color="text.secondary">Placing orders…</Typography>
        )}

        {step === "done" && placingResult && (
          <Box>
            <Typography color={placingResult.ok ? "success.main" : "error.main"} sx={{ mb: 1 }}>
              {placingResult.ok ? "Orders placed." : placingResult.error || "Some orders failed."}
            </Typography>
            {placingResult.responses.length > 0 && (
              <Typography variant="body2" component="pre" sx={{ whiteSpace: "pre-wrap", fontSize: "0.75rem" }}>
                {JSON.stringify(placingResult.responses, null, 2)}
              </Typography>
            )}
          </Box>
        )}

        {error && (
          <Typography color="error" variant="body2" sx={{ mt: 2 }}>
            {error}
          </Typography>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {step === "form" && (
          <>
            <Button onClick={handleClose}>Cancel</Button>
            <Button variant="contained" onClick={handleConfirmForm} disabled={validRows.length === 0}>
              Preview
            </Button>
          </>
        )}
        {step === "preview" && (
          <>
            <Button onClick={handleBack}>Back</Button>
            <Button variant="contained" onClick={handlePlaceOrders}>
              Place orders
            </Button>
          </>
        )}
        {step === "done" && (
          <Button variant="contained" onClick={handleClose}>
            Close
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};
