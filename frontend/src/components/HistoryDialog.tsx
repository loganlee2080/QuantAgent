import React, { useCallback, useEffect, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

const PREVIEW_LEN = 60;

function truncate(s: string, max: number): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max) + "…";
}

function formatTime(createdAt: string | null | undefined): string {
  if (!createdAt) return "—";
  try {
    const d = new Date(createdAt);
    if (Number.isNaN(d.getTime())) return createdAt;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return createdAt;
  }
}

interface OrderRow {
  time?: string;
  orderId?: string;
  symbol?: string;
  orderType?: string;
  side?: string;
  price?: string;
  avgPrice?: string;
  executed?: string;
  amount?: string;
  triggerConditions?: string;
  status?: string;
}

interface ChatRecord {
  created_at?: string | null;
  user_message?: string;
  claude_reply?: string;
  orders_csv?: string | null;
}

interface HistoryDialogProps {
  open: boolean;
  mode: "orders" | "chat";
  onClose: () => void;
}

export const HistoryDialog: React.FC<HistoryDialogProps> = ({
  open,
  mode,
  onClose,
}) => {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [chatRecords, setChatRecords] = useState<ChatRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orderMessage, setOrderMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadOrders = useCallback(async () => {
    const resp = await fetch("/api/binance-order-history");
    const json = await resp.json();
    const list = Array.isArray(json.orders) ? json.orders : [];
    const rows = list as OrderRow[];
    rows.sort((a, b) => {
      const ta = (a.time || "").toString();
      const tb = (b.time || "").toString();
      return tb.localeCompare(ta);
    });
    setOrders(rows);
    setOrderMessage(json.message ?? null);
    return json;
  }, []);

  const loadChatHistory = useCallback(async () => {
    const resp = await fetch("/api/chat/history?limit=200");
    if (!resp.ok) throw new Error(`Failed to load chat history (${resp.status})`);
    const json = await resp.json();
    const list = Array.isArray(json.records) ? json.records : [];
    setChatRecords(list);
  }, []);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setLoading(true);
    if (mode === "orders") {
      loadOrders()
        .catch((e) => setError(e instanceof Error ? e.message : "Failed to load order history"))
        .finally(() => setLoading(false));
    } else {
      loadChatHistory()
        .catch((e) => setError(e instanceof Error ? e.message : "Failed to load chat history"))
        .finally(() => setLoading(false));
    }
  }, [open, mode, loadOrders, loadChatHistory]);

  const handleRefreshOrders = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await fetch("/api/refresh-binance-order-history", { method: "POST" });
      await loadOrders();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const title = mode === "orders" ? "Order history" : "Chat history";

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span>{title}</span>
        <IconButton size="small" onClick={onClose} aria-label="Close">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {loading && (
          <Box sx={{ py: 3, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              Loading…
            </Typography>
          </Box>
        )}
        {error && (
          <Box sx={{ py: 2 }}>
            <Typography variant="body2" color="error">
              {error}
            </Typography>
          </Box>
        )}
        {!loading && mode === "orders" && (
          <>
            {orderMessage && (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                {orderMessage}
              </Typography>
            )}
            <Button
              size="small"
              variant="outlined"
              onClick={handleRefreshOrders}
              disabled={refreshing}
              sx={{ mb: 2 }}
            >
              {refreshing ? "Refreshing…" : "Refresh from Binance"}
            </Button>
            {orders.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No order history yet. Ensure BINANCE_API_KEY/SECRET are set and run refresh, or open a position so symbols are queried.
              </Typography>
            ) : (
              <TableContainer sx={{ maxHeight: 440 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Time</TableCell>
                      <TableCell>Symbol</TableCell>
                      <TableCell>Side</TableCell>
                      <TableCell>Type</TableCell>
                      <TableCell>Price</TableCell>
                      <TableCell>Avg price</TableCell>
                      <TableCell>Executed</TableCell>
                      <TableCell>Amount</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Trigger</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.map((row, idx) => (
                      <TableRow key={`${row.orderId ?? idx}-${row.time ?? idx}`}>
                        <TableCell>{row.time ?? "—"}</TableCell>
                        <TableCell>{row.symbol ?? "—"}</TableCell>
                        <TableCell>{row.side ?? "—"}</TableCell>
                        <TableCell>{row.orderType ?? "—"}</TableCell>
                        <TableCell>{row.price ?? "—"}</TableCell>
                        <TableCell>{row.avgPrice ?? "—"}</TableCell>
                        <TableCell>{row.executed ?? "—"}</TableCell>
                        <TableCell>{row.amount ?? "—"}</TableCell>
                        <TableCell>{row.status ?? "—"}</TableCell>
                        <TableCell>{row.triggerConditions ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </>
        )}
        {!loading && mode === "chat" && (
          <>
            {chatRecords.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No chat history yet. Suggestions are logged here after you use the AI Trading Chat.
              </Typography>
            ) : (
              <TableContainer sx={{ maxHeight: 440 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Time</TableCell>
                      <TableCell>User message</TableCell>
                      <TableCell>Reply</TableCell>
                      <TableCell>Orders</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {chatRecords.map((rec, idx) => (
                      <TableRow key={idx}>
                        <TableCell>{formatTime(rec.created_at ?? null)}</TableCell>
                        <TableCell>
                          <Tooltip title={rec.user_message ?? ""}>
                            <span>{truncate(rec.user_message ?? "", PREVIEW_LEN)}</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          <Tooltip title={rec.claude_reply ?? ""}>
                            <span>{truncate(rec.claude_reply ?? "", PREVIEW_LEN)}</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell>{rec.orders_csv?.trim() ? "Yes" : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
