import React, { useEffect, useState } from "react";
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

export interface OrderHistoryRow {
  time: string;
  symbol: string;
  orderType: string;
  side: string;
  price: string;
  avgPrice: string;
  executed: string;
  amount: string;
  triggerConditions: string;
  status: string;
}

export const OrderHistoryTable: React.FC = () => {
  const [rows, setRows] = useState<OrderHistoryRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setMessage(null);
      try {
        const resp = await fetch("/api/binance-order-history");
        const json = await resp.json();
        setRows(Array.isArray(json.orders) ? json.orders : []);
        if (json.message) setMessage(json.message);
      } catch (e) {
        console.error("Failed to load order history", e);
        setMessage("Failed to load order history.");
      }
    };
    load();
  }, []);

  return (
    <Box>
      {message && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {message}
        </Typography>
      )}
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
              <TableCell>Time</TableCell>
              <TableCell>Symbol</TableCell>
              <TableCell>Order Type</TableCell>
              <TableCell>Side</TableCell>
              <TableCell align="right">Price</TableCell>
              <TableCell align="right">Avg Price</TableCell>
              <TableCell align="right">Executed</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell>Trigger Conditions</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r, idx) => (
              <TableRow key={`${r.time}-${r.symbol}-${idx}`} hover>
                <TableCell>{r.time}</TableCell>
                <TableCell>{r.symbol}</TableCell>
                <TableCell>{r.orderType}</TableCell>
                <TableCell
                  sx={{
                    color: (r.side || "").toUpperCase() === "SELL" ? "error.main" : "success.main",
                  }}
                >
                  {r.side}
                </TableCell>
                <TableCell align="right">{r.price}</TableCell>
                <TableCell align="right">{r.avgPrice}</TableCell>
                <TableCell align="right">{r.executed}</TableCell>
                <TableCell align="right">{r.amount}</TableCell>
                <TableCell>{r.triggerConditions}</TableCell>
                <TableCell
                  sx={{
                    color:
                      (r.status || "").toLowerCase() === "filled" ? "success.main" : "text.primary",
                  }}
                >
                  {r.status}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};
