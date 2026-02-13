import React, { useState } from "react";
import {
  Box,
  Button,
  Divider,
  IconButton,
  List,
  ListItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ChatMessage {
  from: "user" | "bot";
  text: string;
  isExecute?: boolean;
  executeSuccess?: boolean;
  numOrders?: number;
}

export interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
  onExecuteComplete?: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ open, onClose, onExecuteComplete }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");

  const renderWithOrderBlocks = (text: string) => {
    const startMarker = "ORDERS_CSV_START";
    const endMarker = "ORDERS_CSV_END";
    const parts: React.ReactNode[] = [];

    let remaining = text;
    // Simple loop to find all CSV blocks
    while (true) {
      const startIdx = remaining.indexOf(startMarker);
      if (startIdx === -1) {
        // Rest is normal markdown
        if (remaining.trim()) {
          parts.push(
            <ReactMarkdown key={parts.length} remarkPlugins={[remarkGfm]}>
              {remaining}
            </ReactMarkdown>,
          );
        }
        break;
      }
      const endIdx = remaining.indexOf(endMarker, startIdx);
      if (endIdx === -1) {
        // No closing marker; treat as plain markdown
        parts.push(
          <ReactMarkdown key={parts.length} remarkPlugins={[remarkGfm]}>
            {remaining}
          </ReactMarkdown>,
        );
        break;
      }

      const before = remaining.slice(0, startIdx);
      if (before.trim()) {
        parts.push(
          <ReactMarkdown key={parts.length} remarkPlugins={[remarkGfm]}>
            {before}
          </ReactMarkdown>,
        );
      }

      const blockContent = remaining
        .slice(startIdx + startMarker.length, endIdx)
        .trim()
        .replace(/^\s+|\s+$/g, "");

      const csvText = blockContent;
      const CSV_HEADER = "currency,size_usdt,direct,lever";
      const firstLine = csvText.split("\n")[0]?.trim().toLowerCase() ?? "";
      const withHeader =
        firstLine === CSV_HEADER.toLowerCase()
          ? csvText
          : `${CSV_HEADER}\n${csvText.trimStart()}`;

      parts.push(
        <Box
          key={`orders-${parts.length}`}
          sx={{
            mt: 1,
            mb: 1,
            p: 1,
            borderRadius: 1,
            bgcolor: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.12)",
          }}
        >
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ mb: 0.5 }}
          >
            <Typography variant="caption" color="text.secondary">
              Suggested orders (CSV)
            </Typography>
            <Tooltip title="Copy CSV to clipboard (with header)">
              <Button
                size="small"
                variant="outlined"
                sx={{ textTransform: "none" }}
                onClick={() => {
                  void navigator.clipboard.writeText(withHeader);
                }}
              >
                Copy
              </Button>
            </Tooltip>
          </Stack>
          <Box
            component="pre"
            sx={{
              m: 0,
              p: 1,
              borderRadius: 0.5,
              bgcolor: "rgba(0,0,0,0.6)",
              fontFamily: "monospace",
              fontSize: 12,
              overflowX: "auto",
              whiteSpace: "pre",
            }}
          >
            {csvText}
          </Box>
        </Box>,
      );

      remaining = remaining.slice(endIdx + endMarker.length);
    }

    return parts;
  };

  const callChatApi = async (text: string, mode?: string) => {
    setMessages((prev) => [...prev, { from: "user", text }]);
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, mode })
      });
      const data = await resp.json();
      const reply = data.reply ?? "(no reply)";
      const isExecute = Boolean(data.executed);
      const executeSuccess = Boolean(data.success);
      const numOrders = typeof data.num_orders === "number" ? data.num_orders : undefined;
      setMessages((prev) => [
        ...prev,
        {
          from: "bot",
          text: reply,
          ...(isExecute && {
            isExecute: true,
            executeSuccess,
            numOrders,
          }),
        },
      ]);
      if (isExecute && executeSuccess && onExecuteComplete) {
        onExecuteComplete();
      }
    } catch (e) {
      setMessages((prev) => [...prev, { from: "bot", text: "Error talking to backend." }]);
    }
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    setInput("");
    await callChatApi(trimmed, "chat");
  };

  const handleApplyLastSuggestion = async () => {
    await callChatApi("apply last suggestion", "apply_last");
  };

  const handleSuggest = async () => {
    const trimmed = input.trim();
    const msg =
      trimmed ||
      "Suggest position changes to improve risk/return. Return recommended orders as CSV between ORDERS_CSV_START and ORDERS_CSV_END.";
    setInput("");
    await callChatApi(msg, "suggest");
  };

  const handleExecute = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    await callChatApi(trimmed, "execute");
    setInput("");
  };

  if (!open) return null;

  return (
    <Paper
      elevation={3}
      sx={{
        height: "100vh",
        borderLeft: 1,
        borderColor: "divider",
        display: "flex",
        flexDirection: "column"
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1
        }}
      >
        <Typography variant="subtitle1">AI Trading Chat</Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
      <Divider />
      <Box
        sx={{
          flex: 1,
          overflowY: "auto",
          px: 2,
          py: 1,
          scrollbarWidth: "none",
          msOverflowStyle: "none",
          "&::-webkit-scrollbar": { display: "none" },
        }}
      >
        <List dense sx={{ pr: 1 }}>
          {messages.map((m, idx) => (
            <ListItem key={idx} sx={{ justifyContent: "flex-start" }}>
              {m.isExecute ? (
                <Box
                  sx={{
                    width: "100%",
                    borderRadius: 1.5,
                    overflow: "hidden",
                    borderLeft: "4px solid",
                    borderColor: m.executeSuccess ? "success.main" : "error.main",
                    bgcolor: m.executeSuccess
                      ? "rgba(76, 175, 80, 0.08)"
                      : "rgba(244, 67, 54, 0.08)",
                    "& a": { color: "primary.light" },
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      display: "block",
                      px: 1.5,
                      pt: 1,
                      fontWeight: 600,
                      color: m.executeSuccess ? "success.main" : "error.main",
                    }}
                  >
                    {m.executeSuccess
                      ? `✓ Executed ${m.numOrders ?? "?"} order(s)`
                      : "✗ Execution failed"}
                  </Typography>
                  <Box
                    component="pre"
                    sx={{
                      m: 0,
                      p: 1.5,
                      fontSize: 12,
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      overflowX: "auto",
                      scrollbarWidth: "none",
                      msOverflowStyle: "none",
                      "&::-webkit-scrollbar": { display: "none" },
                      bgcolor: "rgba(0,0,0,0.25)",
                      borderTop: "1px solid",
                      borderColor: "divider",
                    }}
                  >
                    {m.text}
                  </Box>
                </Box>
              ) : (
                <Box
                  sx={{
                    maxWidth: "100%",
                    px: 1.25,
                    py: 0.9,
                    borderRadius: 1.5,
                    bgcolor: m.from === "user" ? "rgba(255,255,255,0.04)" : "transparent",
                    border: m.from === "user" ? "1px solid rgba(255,255,255,0.12)" : "none",
                    boxShadow: m.from === "user" ? 1 : 0,
                    fontSize: 13,
                    whiteSpace: "pre-wrap",
                    overflowX: "auto",
                    scrollbarWidth: "none",
                    msOverflowStyle: "none",
                    "&::-webkit-scrollbar": { display: "none" },
                    "& a": { color: "primary.light" },
                    "& code": {
                      fontFamily: "monospace",
                      bgcolor: "rgba(255,255,255,0.08)",
                      px: 0.5,
                      borderRadius: 0.5
                    }
                  }}
                >
                  {renderWithOrderBlocks(m.text)}
                </Box>
              )}
            </ListItem>
          ))}
        </List>
      </Box>
      <Divider />
      <Box sx={{ p: 1 }}>
        <Stack spacing={1}>
          <TextField
            size="small"
            multiline
            minRows={2}
            maxRows={4}
            fullWidth
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Ask about positions or request an order..."
          />
          <Stack direction="row" spacing={1} justifyContent="space-between" flexWrap="wrap" sx={{ width: "100%" }}>
            <Button variant="outlined" size="small" onClick={handleSuggest}>
              Suggest
            </Button>
            <Button
              variant="outlined"
              size="small"
              color="success"
              onClick={handleExecute}
              disabled={!input.trim()}
            >
              Execute
            </Button>
          </Stack>
        </Stack>
      </Box>
    </Paper>
  );
};

