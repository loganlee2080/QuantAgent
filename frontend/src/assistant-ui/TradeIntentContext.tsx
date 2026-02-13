"use client";

import React, { createContext, useContext } from "react";

export interface TradeIntentContextValue {
  /** When set, the chat should show these as trade intent and ask the LLM to summarize + next step. */
  pendingTradeCurrencies: string[] | null;
  /** Open the chat panel and set trade intent so the LLM gets context. */
  openChatWithTrade: (currencies: string[]) => void;
  /** Called by Thread after consuming the intent (append + send). */
  consumeTradeIntent: () => void;
}

export const TradeIntentContext = createContext<TradeIntentContextValue | null>(null);

export function useTradeIntent() {
  return useContext(TradeIntentContext);
}
