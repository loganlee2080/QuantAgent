"use client";

import React, { useState } from "react";
import { Box, IconButton } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ChatIcon from "@mui/icons-material/Chat";
import { Thread } from "./Thread";

interface AssistantSidebarProps {
  children: React.ReactNode;
  /** Controlled open state (when provided, sidebar is controlled). */
  open?: boolean;
  /** Called when user opens/closes the sidebar (for controlled mode). */
  onOpenChange?: (open: boolean) => void;
  /** Uncontrolled: initial open state when open/onOpenChange not provided. */
  defaultOpen?: boolean;
  defaultWidthPercent?: number;
}

export function AssistantSidebar({
  children,
  open: controlledOpen,
  onOpenChange,
  defaultOpen = true,
  defaultWidthPercent = 32,
}: AssistantSidebarProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined && onOpenChange !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const setOpen = isControlled ? onOpenChange! : setInternalOpen;

  const [widthPct, setWidthPct] = useState(defaultWidthPercent);

  const clampedWidth = Math.min(50, Math.max(22, widthPct));

  const handleResize = (deltaPx: number) => {
    const vw = window.innerWidth || 1;
    const deltaPct = (deltaPx / vw) * 100;
    setWidthPct((prev) => Math.min(50, Math.max(22, prev + deltaPct)));
  };

  return (
    <Box sx={{ display: "flex", flex: 1, minHeight: 0, width: "100%" }}>
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {children}
      </Box>
      {open && (
        <>
          <Box
            sx={{
              width: 4,
              cursor: "col-resize",
              bgcolor: "divider",
              flexShrink: 0,
              "&:hover": { bgcolor: "primary.main", opacity: 0.5 },
            }}
            onMouseDown={(e) => {
              e.preventDefault();
              const startX = e.clientX;
              const onMove = (moveEvent: MouseEvent) => handleResize(startX - moveEvent.clientX);
              const onUp = () => {
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup", onUp);
              };
              window.addEventListener("mousemove", onMove);
              window.addEventListener("mouseup", onUp);
            }}
          />
          <Box
            sx={{
              width: `${clampedWidth}%`,
              minWidth: 280,
              maxWidth: "50vw",
              display: "flex",
              flexDirection: "column",
              borderLeft: 1,
              borderColor: "divider",
              bgcolor: "background.paper",
            }}
          >
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                px: 1.5,
                py: 1,
                borderBottom: 1,
                borderColor: "divider",
              }}
            >
              <span style={{ fontWeight: 600, fontSize: "0.95rem" }}>AI Chat</span>
              <IconButton size="small" onClick={() => setOpen(false)} aria-label="Close chat">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>
            <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <Thread />
            </Box>
          </Box>
        </>
      )}
      {!open && (
        <Box
          sx={{
            position: "fixed",
            top: 8,
            right: 8,
            zIndex: 1300,
          }}
        >
          <IconButton
            color="primary"
            onClick={() => setOpen(true)}
            aria-label="Open chat"
            sx={{
              bgcolor: "background.paper",
              boxShadow: 2,
              "&:hover": { bgcolor: "action.hover" },
            }}
          >
            <ChatIcon />
          </IconButton>
        </Box>
      )}
    </Box>
  );
}
