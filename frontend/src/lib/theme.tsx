import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from "react";
export type ThemeMode = "system" | "light" | "dark";
const key = "eh_theme_mode";
function readTheme(): ThemeMode {
  const value = localStorage.getItem(key);
  return value === "dark" || value === "light" ? value : "system";
}
function apply(mode: ThemeMode) {
  document.documentElement.classList.toggle(
    "dark",
    mode === "dark" ||
      (mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches),
  );
}
export function bootstrapTheme() {
  apply(readTheme());
}
const ThemeContext = createContext<{
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}>({ mode: "system", setMode: () => {} });
export function ThemeProvider({ children }: PropsWithChildren) {
  const [mode, setMode] = useState<ThemeMode>(readTheme);
  useEffect(() => {
    apply(mode);
    localStorage.setItem(key, mode);
    const media = matchMedia("(prefers-color-scheme: dark)");
    const change = () => apply(mode);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, [mode]);
  return (
    <ThemeContext.Provider value={{ mode, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
}
export const useAppTheme = () => useContext(ThemeContext);
