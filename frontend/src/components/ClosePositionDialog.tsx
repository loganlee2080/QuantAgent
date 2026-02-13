import React, { useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Radio,
  RadioGroup,
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

export interface PositionRowForClose {
  coin: string;
  szi: string;
  direct: string;
  entryPx: string;
  positionValue: string;
  unrealizedPnl: string;
  markPrice: string;
}

export type CloseOrderType = "MARKET" | "LIMIT";

export interface ClosePositionOptions {
  orderType: CloseOrderType;
  useMarkPrice?: boolean;
  limitPrice?: number;
}

interface ClosePositionDialogProps {
  open: boolean;
  onClose: () => void;
  positions: PositionRowForClose[];
  onConfirm: (options: ClosePositionOptions) => Promise<void>;
}

function formatNum(value: string | undefined): string {
  if (value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toFixed(2);
}

export const ClosePositionDialog: React.FC<ClosePositionDialogProps> = ({
  open,
  onClose,
  positions,
  onConfirm,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orderType, setOrderType] = useState<CloseOrderType>("MARKET");
  const [useMarkPrice, setUseMarkPrice] = useState(true);
  const [limitPriceStr, setLimitPriceStr] = useState("");

  const totalPositionValue = positions.reduce((sum, p) => sum + (Number(p.positionValue) || 0), 0);
  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + (Number(p.unrealizedPnl) || 0), 0);

  const handleConfirm = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const limitPrice = limitPriceStr.trim() ? parseFloat(limitPriceStr) : undefined;
      await onConfirm({
        orderType,
        useMarkPrice: orderType === "LIMIT" ? useMarkPrice : undefined,
        limitPrice: orderType === "LIMIT" && !useMarkPrice && limitPrice !== undefined ? limitPrice : undefined,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to close positions.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        Close position(s)
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {positions.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No positions with size selected. Select positions with non-zero size in the table to close.
          </Typography>
        ) : (
          <>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          The following position(s) will be closed (100% of size). Choose order type and confirm.
        </Typography>
        <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.5 }}>
          Trade type
        </Typography>
        <RadioGroup
          row
          value={orderType}
          onChange={(_, v) => setOrderType(v as CloseOrderType)}
          sx={{ mb: 1 }}
        >
          <FormControlLabel value="MARKET" control={<Radio size="small" />} label="Market order" />
          <FormControlLabel value="LIMIT" control={<Radio size="small" />} label="Limit price order" />
        </RadioGroup>
        {orderType === "LIMIT" && (
          <Box sx={{ mb: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={useMarkPrice}
                  onChange={(_, c) => setUseMarkPrice(c)}
                />
              }
              label="Use current mark price as limit price"
            />
            {!useMarkPrice && (
              <TextField
                size="small"
                type="number"
                label="Limit price"
                value={limitPriceStr}
                onChange={(e) => setLimitPriceStr(e.target.value)}
                inputProps={{ step: "any", min: 0 }}
                sx={{ mt: 1, minWidth: 160 }}
              />
            )}
          </Box>
        )}
        <TableContainer sx={{ maxHeight: 320 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Coin</TableCell>
                <TableCell>Side</TableCell>
                <TableCell align="right">Size</TableCell>
                <TableCell align="right">Entry</TableCell>
                <TableCell align="right">Mark</TableCell>
                <TableCell align="right">Position (USDT)</TableCell>
                <TableCell align="right">Unrealized PnL</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={p.coin}>
                  <TableCell>{p.coin}</TableCell>
                  <TableCell>{p.direct}</TableCell>
                  <TableCell align="right">{p.szi}</TableCell>
                  <TableCell align="right">{formatNum(p.entryPx)}</TableCell>
                  <TableCell align="right">{formatNum(p.markPrice)}</TableCell>
                  <TableCell align="right">{formatNum(p.positionValue)}</TableCell>
                  <TableCell align="right">{formatNum(p.unrealizedPnl)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <TableContainer component={Box} sx={{ mt: 1, borderTop: 1, borderColor: "divider" }}>
          <Table size="small">
            <TableBody>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>Total</TableCell>
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell align="right" sx={{ fontWeight: 600 }}>
                  {formatNum(String(totalPositionValue))} USDT
                </TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>
                  {formatNum(String(totalUnrealizedPnl))} USDT
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
        {error && (
          <Typography color="error" variant="body2" sx={{ mt: 2 }}>
            {error}
          </Typography>
        )}
          </>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          color="primary"
          onClick={handleConfirm}
          disabled={submitting || positions.length === 0}
        >
          {submitting ? "Closing…" : "Confirm"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
