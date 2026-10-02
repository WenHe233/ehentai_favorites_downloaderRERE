import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppTheme } from "@/lib/theme";
export default function ThemeToggle() {
  const { mode, setMode } = useAppTheme();
  const Icon = mode === "dark" ? Moon : mode === "light" ? Sun : Monitor;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="切换主题">
          <Icon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {(["light", "dark", "system"] as const).map((value) => (
          <DropdownMenuItem key={value} onClick={() => setMode(value)}>
            {{ light: "浅色", dark: "深色", system: "跟随系统" }[value]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
