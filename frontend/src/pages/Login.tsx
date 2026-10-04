import { useState } from "react";
import { ArrowRight } from "lucide-react";
import AppBrandIcon from "@/components/AppBrandIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorPanel } from "@/components/common";
import ThemeToggle from "@/components/ThemeToggle";
import ApiConnectionSettings from "@/components/ApiConnectionSettings";
import api from "@/lib/api";
import { setAuthToken } from "@/lib/auth";
export default function Login({
  onLoginSuccess,
}: {
  onLoginSuccess: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  return (
    <main className="flex min-h-svh items-center justify-center p-6">
      <div className="absolute right-6 top-6">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm space-y-8">
        <div>
          <AppBrandIcon size={64} className="mb-6" />
          <p className="text-xs font-medium tracking-[.2em] text-muted-foreground">
            EFDRR
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">
            登录收藏控制台
          </h1>
          <p className="page-description">管理收藏同步、下载任务和归档。</p>
        </div>
        <Card>
          <CardContent className="pt-6">
            <form
              className="space-y-5"
              onSubmit={async (event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                setBusy(true);
                setError(undefined);
                try {
                  const response = await api.post("/auth/login", {
                    username: data.get("username"),
                    password: data.get("password"),
                  });
                  if (response.data.access_token)
                    setAuthToken(response.data.access_token);
                  onLoginSuccess();
                } catch (error) {
                  setError(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <div className="field">
                <Label htmlFor="username">用户名</Label>
                <Input
                  id="username"
                  name="username"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </div>
              <div className="field">
                <Label htmlFor="password">密码</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </div>
              {error !== undefined && <ErrorPanel error={error} />}
              <Button className="w-full" disabled={busy}>
                {busy ? "正在登录…" : "登录"}
                <ArrowRight />
              </Button>
            </form>
          </CardContent>
        </Card>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>v{__APP_VERSION__}</span>
          <ApiConnectionSettings />
        </div>
      </div>
    </main>
  );
}
