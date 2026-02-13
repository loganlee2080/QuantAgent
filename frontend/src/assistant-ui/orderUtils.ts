const ORDERS_CSV_START = "ORDERS_CSV_START";
const ORDERS_CSV_END = "ORDERS_CSV_END";

/**
 * Extract CSV block between ORDERS_CSV_START and ORDERS_CSV_END from assistant message text.
 * Returns null if not found or empty.
 */
export function extractOrdersCsvFromMessage(text: string | undefined): string | null {
  if (!text || typeof text !== "string") return null;
  const startIdx = text.indexOf(ORDERS_CSV_START);
  if (startIdx === -1) return null;
  const endIdx = text.indexOf(ORDERS_CSV_END, startIdx);
  if (endIdx === -1) return null;
  const block = text
    .slice(startIdx + ORDERS_CSV_START.length, endIdx)
    .trim();
  const lines = block.split("\n").filter((ln) => ln.trim());
  if (lines.length < 2) return null; // header + at least one row
  return block;
}

export type OrderRow = {
  currency: string;
  sizeUsdt: number;
  direct: string;
  lever: number | null;
};

/**
 * Parse an ORDERS_CSV block (without markers) into structured rows.
 * Very small CSV parser, assuming comma-separated and the standard header.
 */
export function parseOrdersCsv(csvBlock: string | null | undefined): OrderRow[] {
  if (!csvBlock) return [];
  const lines = csvBlock
    .split("\n")
    .map((ln) => ln.trim())
    .filter((ln) => ln && !ln.startsWith("#"));
  if (lines.length < 2) return [];
  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const idxCurrency = header.indexOf("currency");
  const idxSize = header.indexOf("size_usdt");
  const idxDirect = header.indexOf("direct");
  const idxLever = header.indexOf("lever");
  if (idxCurrency === -1 || idxSize === -1 || idxDirect === -1) return [];

  const rows: OrderRow[] = [];
  for (const line of lines.slice(1)) {
    const cols = line.split(",").map((c) => c.trim());
    const currency = (cols[idxCurrency] || "").toUpperCase();
    const sizeStr = cols[idxSize] || "";
    const direct = cols[idxDirect] || "";
    const leverStr = idxLever >= 0 ? cols[idxLever] || "" : "";
    if (!currency || !sizeStr || !direct) continue;
    const sizeVal = Number(sizeStr);
    if (!Number.isFinite(sizeVal) || sizeVal === 0) continue;
    const leverVal = leverStr ? Number(leverStr) : null;
    rows.push({
      currency,
      sizeUsdt: sizeVal,
      direct,
      lever: Number.isFinite(leverVal as number) ? (leverVal as number) : null,
    });
  }
  return rows;
}
