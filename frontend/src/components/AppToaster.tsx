import { Toaster } from "sonner";
import { useAppTheme } from "@/lib/theme";

export default function AppToaster() {
  const { mode } = useAppTheme();
  return <Toaster theme={mode} richColors position="bottom-right" />;
}
