import React, { useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  Divider,
  IconButton,
  Stack,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

interface ChatPanelV2Props {
  open: boolean;
  onClose: () => void;
  onExecuteComplete?: () => void;
}

interface ChatEventMessage {
  role: "user" | "assistant" | "system";
  content: string;
  executed?: boolean;
  success?: boolean;
  num_orders?: number;
  orders?: ParsedOrder[];
}

interface ParsedOrder {
  currency: string;
  size_usdt: number;
  direct: string;
  lever?: string;
}

const extractOrdersFromText = (text: string): ParsedOrder[] => {
  const start = text.indexOf("ORDERS_CSV_START");
  const end = text.indexOf("ORDERS_CSV_END", start === -1 ? 0 : start);
  if (start === -1 || end === -1) return [];
  const block = text.slice(start + "ORDERS_CSV_START".length, end).trim();
  const lines = block
    .split("\n")
    .map((ln) => ln.trim())
    .filter((ln) => ln && !ln.startsWith("#"));
  if (!lines.length) return [];
  const rows: ParsedOrder[] = [];
  for (const line of lines) {
    const [currencyRaw, sizeStr, directRaw, leverRaw] = line.split(",").map((v) => (v || "").trim());
    const currency = currencyRaw || "";
    if (!currency || !sizeStr || !directRaw) continue;
    const size = Number(sizeStr);
    if (!Number.isFinite(size) || size <= 0) continue;
    rows.push({
      currency,
      size_usdt: size,
      direct: directRaw,
      lever: leverRaw || undefined,
    });
  }
  return rows;
};

const ordersToCsv = (orders: ParsedOrder[]): string => {
  if (!orders.length) return "";
  const header = "currency,size_usdt,direct,lever";
  const lines = orders.map((o) =>
    [
      o.currency,
      Number.isFinite(o.size_usdt) ? String(o.size_usdt) : "",
      o.direct,
      o.lever ?? "",
    ].join(","),
  );
  return [header, ...lines].join("\n");
};

const summarizeExecutionReply = (reply: string, numOrders?: number): string => {
  const lines = reply
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    if (numOrders != null) return `Execution finished for ${numOrders} order(s).`;
    return "Execution finished.";
  }
  const first = lines[0];
  if (numOrders != null && !first.toLowerCase().includes("order")) {
    return `${first} (${numOrders} order${numOrders === 1 ? "" : "s"})`;
  }
  return first;
};

const parseEventData = (raw: string): any => {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
};

export const ChatPanelV2: React.FC<ChatPanelV2Props> = ({
  open,
  onClose,
  onExecuteComplete,
}) => {
  const [messages, setMessages] = useState<ChatEventMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [lastOrdersCsv, setLastOrdersCsv] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [sessionId] = useState<string>(() => {
    const key = "cq_chat_session_id";
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const v = `sess_${Math.random().toString(36).slice(2)}`;
    window.localStorage.setItem(key, v);
    return v;
  });

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const handleSend = async (mode: "chat" | "suggest" | "execute" = "chat") => {
    const trimmed = input.trim();
    if (!trimmed && mode === "chat") return;
    const text =
      trimmed ||
      "Suggest position changes and return CSV between ORDERS_CSV_START and ORDERS_CSV_END.";

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    if (mode === "execute") {
      setMessages((prev) => [
        ...prev,
        { role: "system", content: "Executing orders via binance_trade_api.py..." },
      ]);
    }
    setInput("");
    setIsRunning(true);

    try {
      const resp = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, mode, session_id: sessionId }),
      });

      if (!resp.body) {
        setIsRunning(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantBuffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx).trimEnd();
          buffer = buffer.slice(idx + 2);
          if (!chunk) continue;
          const lines = chunk.split("\n");
          let eventType = "message";
          let dataLine = "";
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice("event:".length).trim();
            } else if (line.startsWith("data:")) {
              dataLine = line.slice("data:".length).trim();
            }
          }
          if (!dataLine) continue;
          const payload = parseEventData(dataLine);
          if (eventType === "error") {
            assistantBuffer = payload.error || "Error in chat stream.";
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: assistantBuffer },
            ]);
          } else if (eventType === "message") {
            const reply = String(payload.reply ?? "");
            assistantBuffer = reply;
            const executed = Boolean(payload.executed);
            const success = Boolean(payload.success);
            const numOrders =
              typeof payload.num_orders === "number" ? payload.num_orders : undefined;
            const parsedOrders = executed ? [] : extractOrdersFromText(reply);
            if (parsedOrders.length > 0) {
              setLastOrdersCsv(ordersToCsv(parsedOrders));
            }
            const content = executed
              ? summarizeExecutionReply(reply, numOrders)
              : reply;
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content,
                executed,
                success,
                num_orders: numOrders,
                orders: parsedOrders.length ? parsedOrders : undefined,
              },
            ]);
            if (executed && success && onExecuteComplete) {
              void onExecuteComplete();
            }
          }
        }
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Error talking to backend." },
      ]);
    } finally {
      setIsRunning(false);
    }
  };

  const handleExecuteOrders = () => {
    if (!lastOrdersCsv) return;
    setInput(lastOrdersCsv);
    void handleSend("execute");
  };

  const handleExecuteOrdersForMessage = async (orders: ParsedOrder[]) => {
    if (!orders.length) return;
    const csvText = ordersToCsv(orders);
    setMessages((prev) => [
      ...prev,
      {
        role: "system",
        content: `Executing ${orders.length} order(s) via binance_trade_api.py...`,
      },
    ]);
    setIsRunning(true);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: csvText, mode: "execute", session_id: sessionId }),
      });
      const data = await resp.json();
      const reply = String(data.reply ?? "");
      const executed = Boolean(data.executed);
      const success = Boolean(data.success);
      const numOrders =
        typeof data.num_orders === "number" ? data.num_orders : orders.length;
      const content =
        executed && !success ? reply : summarizeExecutionReply(reply, numOrders);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content,
          executed,
          success,
          num_orders: numOrders,
          orders: executed ? orders : undefined,
        },
      ]);
      if (executed && success && onExecuteComplete) {
        void onExecuteComplete();
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : "Error executing orders.";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: errMsg,
          executed: true,
          success: false,
          num_orders: orders.length,
          orders,
        },
      ]);
    } finally {
      setIsRunning(false);
    }
  };

  if (!open) return null;

  return (
    <Box
      sx={{
        height: "100%",
        borderLeft: 1,
        borderColor: "divider",
        display: "flex",
        flexDirection: "column",
        pb: 6, // keep bottom input/buttons clear of the global footer
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1,
        }}
      >
        <Typography variant="subtitle1">AI Trading Chat</Typography>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Button
            size="small"
            variant="outlined"
            color="inherit"
            onClick={() => {
              if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
              }
              setMessages([]);
              setInput("");
              setLastOrdersCsv(null);
              setIsRunning(false);
            }}
          >
            Reset
          </Button>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>
      <Divider />
      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          px: 1,
          py: 1,
          overflowY: "auto",
        }}
      >
        {messages.map((m, idx) => {
          const orders = m.role === "assistant" ? m.orders ?? [] : [];
          if (m.executed) {
            const isError = !m.success;
            return (
              <Box
                key={idx}
                sx={{
                  mb: 1,
                  px: 1.25,
                  py: 0.9,
                  borderRadius: 1.5,
                  borderLeft: "4px solid",
                  borderColor: m.success ? "success.main" : "error.main",
                  bgcolor: m.success
                    ? "rgba(76, 175, 80, 0.08)"
                    : "rgba(244, 67, 54, 0.35)",
                  fontSize: 13,
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    mb: 0.25,
                    fontWeight: 600,
                    color: m.success ? "success.main" : "error.main",
                  }}
                >
                  {m.success ? "Execution succeeded" : "Execution failed"}
                  {typeof m.num_orders === "number"
                    ? ` · ${m.num_orders} order${m.num_orders === 1 ? "" : "s"}`
                    : ""}
                </Typography>
                <Typography
                  variant="body2"
                  component="pre"
                  sx={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    ...(isError && {
                      color: "rgba(255,255,255,0.95)",
                      fontWeight: 500,
                    }),
                  }}
                >
                  {m.content}
                </Typography>
                {isError && (m.orders?.length ?? 0) > 0 && (
                  <Button
                    variant="outlined"
                    size="small"
                    color="error"
                    sx={{ mt: 1 }}
                    disabled={isRunning}
                    onClick={() =>
                      handleExecuteOrdersForMessage(m.orders!)
                    }
                  >
                    Retry
                  </Button>
                )}
              </Box>
            );
          }
          return (
            <Box
              key={idx}
              sx={{
                mb: 1,
                px: 1.25,
                py: 0.75,
                borderRadius: 1.5,
                bgcolor:
                  m.role === "user" ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
                border:
                  m.role === "user"
                    ? "1px solid rgba(255,255,255,0.16)"
                    : "1px solid rgba(255,255,255,0.06)",
                fontSize: 13,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              <Typography
                variant="caption"
                sx={{ display: "block", mb: 0.25, opacity: 0.7 }}
              >
                {m.role === "user" ? "You" : "Agent"}
              </Typography>
              <Typography variant="body2">{m.content}</Typography>
              {orders.length > 0 && (
                <Box
                  sx={{
                    mt: 1,
                    borderRadius: 1,
                    bgcolor: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.12)",
                  }}
                >
                  <Box
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      px: 1,
                      py: 0.5,
                    }}
                  >
                    <Typography
                      variant="caption"
                      sx={{ opacity: 0.8, fontWeight: 600 }}
                    >
                      Suggested orders (editable)
                    </Typography>
                    <Button
                      variant="contained"
                      size="small"
                      color="success"
                      disabled={isRunning}
                      onClick={() => void handleExecuteOrdersForMessage(orders)}
                    >
                      Execute these orders
                    </Button>
                  </Box>
                  <TableContainer sx={{ maxHeight: 220 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ fontSize: 11 }}>Currency</TableCell>
                          <TableCell sx={{ fontSize: 11 }}>Size (USDT)</TableCell>
                          <TableCell sx={{ fontSize: 11 }}>Direct</TableCell>
                          <TableCell sx={{ fontSize: 11 }}>Lever</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {orders.map((o, rowIdx) => (
                          <TableRow key={`${o.currency}-${rowIdx}`}>
                            <TableCell sx={{ fontSize: 12 }}>
                              <TextField
                                variant="standard"
                                value={o.currency}
                                onChange={(e) => {
                                  const next = [...orders];
                                  next[rowIdx] = { ...next[rowIdx], currency: e.target.value.toUpperCase() };
                                  setMessages((prev) =>
                                    prev.map((msg, i) =>
                                      i === idx ? { ...msg, orders: next } : msg,
                                    ),
                                  );
                                  setLastOrdersCsv(ordersToCsv(next));
                                }}
                                inputProps={{ style: { fontSize: 12 } }}
                              />
                            </TableCell>
                            <TableCell sx={{ fontSize: 12 }}>
                              <TextField
                                variant="standard"
                                type="number"
                                value={Number.isFinite(o.size_usdt) ? o.size_usdt : ""}
                                onChange={(e) => {
                                  const val = Number(e.target.value);
                                  const next = [...orders];
                                  next[rowIdx] = {
                                    ...next[rowIdx],
                                    size_usdt: Number.isFinite(val) ? val : 0,
                                  };
                                  setMessages((prev) =>
                                    prev.map((msg, i) =>
                                      i === idx ? { ...msg, orders: next } : msg,
                                    ),
                                  );
                                  setLastOrdersCsv(ordersToCsv(next));
                                }}
                                inputProps={{ style: { fontSize: 12 } }}
                              />
                            </TableCell>
                            <TableCell sx={{ fontSize: 12 }}>
                              <TextField
                                variant="standard"
                                value={o.direct}
                                onChange={(e) => {
                                  const next = [...orders];
                                  next[rowIdx] = { ...next[rowIdx], direct: e.target.value };
                                  setMessages((prev) =>
                                    prev.map((msg, i) =>
                                      i === idx ? { ...msg, orders: next } : msg,
                                    ),
                                  );
                                  setLastOrdersCsv(ordersToCsv(next));
                                }}
                                inputProps={{ style: { fontSize: 12 } }}
                              />
                            </TableCell>
                            <TableCell sx={{ fontSize: 12 }}>
                              <TextField
                                variant="standard"
                                value={o.lever ?? ""}
                                onChange={(e) => {
                                  const next = [...orders];
                                  next[rowIdx] = { ...next[rowIdx], lever: e.target.value };
                                  setMessages((prev) =>
                                    prev.map((msg, i) =>
                                      i === idx ? { ...msg, orders: next } : msg,
                                    ),
                                  );
                                  setLastOrdersCsv(ordersToCsv(next));
                                }}
                                inputProps={{ style: { fontSize: 12 } }}
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}
            </Box>
          );
        })}
      </Box>
      <Divider />
      <Box sx={{ p: 1 }}>
        <Stack spacing={1}>
          <textarea
            rows={3}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            style={{
              width: "100%",
              resize: "none",
              padding: "8px 10px",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.16)",
              background: "transparent",
              color: "inherit",
              font: "inherit",
            }}
            placeholder="Ask about positions or request an order..."
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend("chat");
              }
            }}
          />
        </Stack>
      </Box>
    </Box>
  );
}

