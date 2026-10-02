import { useState, type ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { errorText } from "@/lib/query";
export function Loading() {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-3 p-16 text-sm text-muted-foreground"
    >
      <Loader2 className="size-5 animate-spin" />
      加载中
    </div>
  );
}
export function ErrorPanel({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm"
    >
      <AlertCircle className="size-4 text-destructive" />
      <span className="flex-1">{errorText(error)}</span>
      {retry && (
        <Button variant="outline" size="sm" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  );
}
export function ConfirmAction({
  children,
  title,
  description,
  action,
}: {
  children: ReactNode;
  title: string;
  description: string;
  action: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      await action();
      setOpen(false);
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() => void run()}
          >
            {busy ? "处理中…" : "确认"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
