import { Progress } from "@/components/ui/progress";
import type { GalleryProgress } from "@/lib/download-events";
export default function GalleryProgressPanel({
  progress,
  compact = false,
}: {
  progress?: GalleryProgress | null;
  compact?: boolean;
}) {
  if (!progress) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="min-w-28 space-y-2">
      <div className="flex justify-between gap-2 text-xs">
        <span
          className="truncate text-muted-foreground"
          title={progress.detail}
        >
          {progress.detail || "等待下载"}
        </span>
        <span className="tabular-nums">{Math.round(progress.percent)}%</span>
      </div>
      <Progress value={progress.percent} className="h-1.5" />
      {!compact && progress.total != null && (
        <p className="text-xs text-muted-foreground">
          {progress.current} / {progress.total}{" "}
          {progress.unit === "images"
            ? "张图片"
            : progress.unit === "bytes"
              ? "字节"
              : "项"}
        </p>
      )}
    </div>
  );
}
