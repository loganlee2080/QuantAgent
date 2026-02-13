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

export interface FundingFeeRow {
  time: string;
  asset: string;
  amount: string;
  symbol: string;
}

export const FundingFeeTable: React.FC = () => {
  const [rows, setRows] = useState<FundingFeeRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setMessage(null);
      try {
        const resp = await fetch("/api/binance-funding-fee-history");
        const json = await resp.json();
        setRows(Array.isArray(json.fundingFees) ? json.fundingFees : []);
        if (json.message) setMessage(json.message);
      } catch (e) {
        console.error("Failed to load funding fee history", e);
        setMessage("Failed to load funding fee history.");
      }
    };
    load();
  }, []);

  const amountColor = (amount: string): "success.main" | "error.main" | "text.primary" => {
    const n = parseFloat(amount);
    if (Number.isNaN(n)) return "text.primary";
    if (n > 0) return "success.main";
    if (n < 0) return "error.main";
    return "text.primary";
  };

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Funding Fee
      </Typography>
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
              <TableCell>Asset</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell>Symbol</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r, idx) => (
              <TableRow key={`${r.time}-${r.symbol}-${idx}`} hover>
                <TableCell>{r.time}</TableCell>
                <TableCell>{r.asset}</TableCell>
                <TableCell align="right" sx={{ color: amountColor(r.amount) }}>
                  {r.amount}
                </TableCell>
                <TableCell>{r.symbol}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};
