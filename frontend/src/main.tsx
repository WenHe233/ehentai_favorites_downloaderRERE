import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";
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
        <Toaster richColors position="bottom-right" />
      </TooltipProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
