import { useState } from "react";
import { Plug } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiBaseUrl, getDefaultApiBaseUrl, setApiBaseUrl } from "@/lib/api";
export default function ApiConnectionSettings({
  buttonText = "连接设置",
  onSaved,
}: {
  buttonText?: string;
  onSaved?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(getApiBaseUrl);
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (value) setValue(getApiBaseUrl());
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Plug />
          {buttonText}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>后端连接</DialogTitle>
          <DialogDescription>
            默认使用同源 /api/v1。更换地址后需要重新登录。
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!value.startsWith("/") && !/^https?:\/\//.test(value)) {
              toast.error("请输入以 /、http:// 或 https:// 开头的 API 地址");
              return;
            }
            setApiBaseUrl(value);
            setOpen(false);
            onSaved?.();
          }}
        >
          <div className="field">
            <Label htmlFor="api-url">API 地址</Label>
            <Input
              id="api-url"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              required
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setValue(getDefaultApiBaseUrl())}
            >
              使用默认值
            </Button>
            <Button type="submit">保存连接</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
