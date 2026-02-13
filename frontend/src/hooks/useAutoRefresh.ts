import { useEffect, useRef } from "react";

export type RefreshInterval = "off" | "5s" | "30s" | "60s";

const intervalToMs: Record<Exclude<RefreshInterval, "off">, number> = {
  "5s": 5000,
  "30s": 30000,
  "60s": 60000
};

export function useAutoRefresh(interval: RefreshInterval, onRefresh: () => void) {
  const callbackRef = useRef(onRefresh);
  callbackRef.current = onRefresh;

  useEffect(() => {
    if (interval === "off") {
      return;
    }
    const ms = intervalToMs[interval];
    const id = window.setInterval(() => {
      callbackRef.current();
    }, ms);
    return () => window.clearInterval(id);
  }, [interval]);
}

