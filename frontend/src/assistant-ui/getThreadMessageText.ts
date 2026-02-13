import type { ThreadMessage } from "@assistant-ui/react";
import type { TextMessagePart } from "@assistant-ui/react";

export function getThreadMessageText(message: ThreadMessage): string {
  const parts = message.content ?? [];
  const textParts = parts.filter((p): p is TextMessagePart => p.type === "text");
  return textParts.map((p) => p.text).join("\n\n");
}
