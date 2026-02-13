"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MessagePartPrimitive } from "@assistant-ui/react";

type TextPartProps = { type: "text"; text?: string };

export function MarkdownTextPart(props: TextPartProps) {
  const text = props.type === "text" ? (props.text ?? "") : "";
  return (
    <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      <MessagePartPrimitive.InProgress>
        <span style={{ fontFamily: "revert" }}> {" \u25CF"}</span>
      </MessagePartPrimitive.InProgress>
    </div>
  );
}
