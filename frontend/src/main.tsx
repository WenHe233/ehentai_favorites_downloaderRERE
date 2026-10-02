import React from "react";
import ReactDOM from "react-dom/client";
import AppToaster from "@/components/AppToaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider, bootstrapTheme } from "@/lib/theme";
import App from "./App";
import "./index.css";
bootstrapTheme();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <TooltipProvider>
        <App />
        <AppToaster />
      </TooltipProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
