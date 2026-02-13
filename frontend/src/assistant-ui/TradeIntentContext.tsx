"use client";

import React, { createContext, useContext } from "react";

export interface TradeIntentContextValue {
  /** When set, the chat should show these as trade intent and ask the LLM to summarize + next step. */
  pendingTradeCurrencies: string[] | null;
  /** Open the chat panel and set trade intent so the LLM gets context. */
  openChatWithTrade: (currencies: string[]) => void;
  /** Called by Thread after consuming the intent (append + send). */
  consumeTradeIntent: () => void;
  /** Pending plain-text prompt to prefill into the chat composer. */
  pendingChatText: string | null;
  /** Open chat (if hidden) and prefill the composer with given text. */
  addTextToChat: (text: string) => void;
  /** Called by Thread after applying pendingChatText into the composer. */
  consumeChatText: () => void;
}

export const TradeIntentContext = createContext<TradeIntentContextValue | null>(null);

export function useTradeIntent() {
  return useContext(TradeIntentContext);
}
