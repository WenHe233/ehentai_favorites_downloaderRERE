import { Badge } from "@/components/ui/badge";
import { statusLabels } from "@/lib/status";
export default function StatusPill({ status }: { status: string }) {
  return (
    <Badge
      variant={
        status === "failed"
          ? "destructive"
          : status === "downloading"
            ? "default"
            : "secondary"
      }
      className={
        status === "completed" || status === "archived"
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20"
          : ""
      }
    >
      {statusLabels[status] || status}
    </Badge>
  );
}
