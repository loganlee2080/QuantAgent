import React, { useState } from "react";
import {
  Box,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography
} from "@mui/material";

export interface OrderMetaRow {
  currency: string;
  quantity_precision: string;
  max_size_usdt: string;
  min_size_usdt: string;
  order_type: string;
  enabled_trade: string;
  default_lever: string;
  notes: string;
}

export const OrderMetaTable: React.FC = () => {
  const [rows] = useState<OrderMetaRow[]>([]);

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Order meta / config
      </Typography>
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
              <TableCell>Currency</TableCell>
              <TableCell align="right">Quantity precision</TableCell>
              <TableCell align="right">Max size (USDT)</TableCell>
              <TableCell align="right">Min size (USDT)</TableCell>
              <TableCell>Order type</TableCell>
              <TableCell>Enabled</TableCell>
              <TableCell align="right">Default leverage</TableCell>
              <TableCell>Notes</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.currency} hover>
                <TableCell>{r.currency}</TableCell>
                <TableCell align="right">{r.quantity_precision}</TableCell>
                <TableCell align="right">{r.max_size_usdt}</TableCell>
                <TableCell align="right">{r.min_size_usdt}</TableCell>
                <TableCell>{r.order_type}</TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={(r.enabled_trade || "").toLowerCase() === "true" ? "enabled" : "disabled"}
                    color={(r.enabled_trade || "").toLowerCase() === "true" ? "success" : "default"}
                    sx={{ bgcolor: "transparent", border: "none" }}
                    variant="outlined"
                  />
                </TableCell>
                <TableCell align="right">{r.default_lever}</TableCell>
                <TableCell>{r.notes}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

