"use client";

import type { AttachmentAdapter } from "@assistant-ui/react";
import type { PendingAttachment, CompleteAttachment } from "@assistant-ui/react";

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function getAttachmentType(file: File): "image" | "document" | "file" {
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf" || file.type.startsWith("text/")) return "document";
  return "file";
}

export const cryptoQuantAttachmentAdapter: AttachmentAdapter = {
  accept: "image/*,application/pdf,text/*",

  async add({ file }): Promise<PendingAttachment> {
    const type = getAttachmentType(file);
    return {
      id: `att_${Math.random().toString(36).slice(2)}`,
      type,
      name: file.name,
      contentType: file.type,
      file,
      status: { type: "requires-action", reason: "composer-send" },
    };
  },

  async remove(): Promise<void> {
    // No server to notify; optional cleanup of object URLs could go here
  },

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    const { file, id, type, name, contentType } = attachment;
    if (type === "image") {
      const dataUrl = await fileToDataUrl(file);
      return {
        id,
        type: "image",
        name,
        contentType,
        status: { type: "complete" },
        content: [{ type: "image", image: dataUrl }],
      };
    }
    // For document/file, include as text or placeholder for backend
    const text = await (async () => {
      if (file.type.startsWith("text/")) {
        return await file.text();
      }
      return `[Attachment: ${name}]`;
    })();
    return {
      id,
      type: type as "document" | "file",
      name,
      contentType,
      status: { type: "complete" },
      content: text ? [{ type: "text", text }] : [],
    };
  },
};
