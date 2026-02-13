import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import { CryptoQuantRuntimeProvider } from "./assistant-ui/CryptoQuantRuntimeProvider";
import App from "./App";

const theme = createTheme({
  palette: {
    mode: "dark",
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: (themeParam) => ({
        "html, body": {
          height: "100%",
          overflow: "hidden",
        },
        body: {
          scrollbarWidth: "none",
          msOverflowStyle: "none",
        },
        "body *": {
          scrollbarWidth: "none",
          msOverflowStyle: "none",
        },
        "body::-webkit-scrollbar, body *::-webkit-scrollbar": {
          width: 0,
          height: 0,
          display: "none",
        },
      }),
    },
  },
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <CryptoQuantRuntimeProvider>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </CryptoQuantRuntimeProvider>
  </React.StrictMode>
);

