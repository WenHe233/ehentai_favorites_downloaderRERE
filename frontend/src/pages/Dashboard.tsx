import { useState } from "react";
import {
  ArrowRight,
  Clock3,
  Download,
  Layers3,
  RefreshCw,
  Wallet,
  Activity,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ErrorPanel, Loading } from "@/components/common";
import StatusPill from "@/components/StatusPill";
import GalleryProgressPanel from "@/components/GalleryProgressPanel";
import { useApi, dateText, errorText } from "@/lib/query";
import api from "@/lib/api";
import {
  useDownloadEventStream,
  type GalleryProgressEvent,
} from "@/lib/download-events";
interface Status {
  downloader_running: boolean;
  queue_len: number;
  active_downloads: number;
  max_concurrent_downloads: number;
  failed_retry_count: number;
  last_sync_ts: string | null;
  sync_running: boolean;
  sync_last_error: string | null;
}
export default function Dashboard() {
  const { data: status, error, mutate } = useApi<Status>("/status", 15000);
  const { data: settings } = useApi<{ ipb_member_id_configured: boolean }>(
    "/settings",
  );
  const { data: account, mutate: refreshAccount } = useApi<{
    gp: number | null;
    credits: number | null;
  }>(settings?.ipb_member_id_configured ? "/account" : null);
  const [active, setActive] = useState<GalleryProgressEvent[]>([]);
  const [urls, setUrls] = useState("");
  const [adding, setAdding] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [results, setResults] = useState<
    { url: string; message: string; success: boolean }[]
  >([]);
  const { connectionState } = useDownloadEventStream({
    onSnapshot: (event) => {
      setActive(event.active_galleries);
      void mutate();
    },
    onGalleryProgress: (event) =>
      setActive((current) => [
        ...current.filter((item) => item.gid !== event.gid),
        event,
      ]),
    onGalleryStatus: (event) => {
      setActive((current) => current.filter((item) => item.gid !== event.gid));
      void mutate();
    },
    onSyncStatus: () => void mutate(),
    onReconnected: () => void mutate(),
  });
  async function sync() {
    setSyncing(true);
    try {
      const { data } = await api.post("/action/sync");
      toast.success(
        data.status === "already_running" ? "同步已在运行" : "已开始同步",
      );
      await mutate();
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setSyncing(false);
    }
  }
  async function add() {
    const list = [...new Set(urls.split(/[\s,，]+/).filter(Boolean))];
    if (!list.length) {
      toast.error("请输入画廊链接");
      return;
    }
    setAdding(true);
    setResults([]);
    for (const url of list) {
      if (
        !/^https:\/\/(e-hentai|exhentai)\.org\/g\/\d+\/[a-zA-Z0-9]+\/?(?:\?.*)?$/.test(
          url,
        )
      ) {
        setResults((current) => [
          ...current,
          { url, message: "链接格式无效", success: false },
        ]);
        continue;
      }
      try {
        const { data } = await api.post(
          "/download/manual",
          { url },
          { timeout: 120000 },
        );
        setResults((current) => [
          ...current,
          { url, message: data.msg, success: true },
        ]);
      } catch (error) {
        setResults((current) => [
          ...current,
          { url, message: errorText(error), success: false },
        ]);
      }
    }
    setAdding(false);
    await mutate();
  }
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[.18em] text-muted-foreground">
            Overview
          </p>
          <h1 className="page-heading">收藏与下载</h1>
          <p className="page-description">查看同步状态，管理正在进行的归档。</p>
        </div>
        <Button
          disabled={syncing || status?.sync_running}
          onClick={() => void sync()}
        >
          <RefreshCw
            className={syncing || status?.sync_running ? "animate-spin" : ""}
          />
          {status?.sync_running ? "正在同步" : "同步收藏夹"}
        </Button>
      </div>
      {error && <ErrorPanel error={error} retry={() => void mutate()} />}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[
          {
            label: "等待下载",
            value: status?.queue_len,
            icon: Layers3,
            detail: "已进入下载队列",
          },
          {
            label: "正在下载",
            value: status?.active_downloads,
            icon: Download,
            detail: "并发上限 " + (status?.max_concurrent_downloads ?? "—"),
          },
          {
            label: "待重试",
            value: status?.failed_retry_count,
            icon: RefreshCw,
            detail: "同步时重新加入队列",
          },
          {
            label: "账户 GP",
            value: account?.gp,
            icon: Wallet,
            detail: settings?.ipb_member_id_configured
              ? "Credits · " + (account?.credits?.toLocaleString() ?? "—")
              : "请先配置账号 Cookie",
          },
        ].map(({ label, value, icon: Icon, detail }) => (
          <Card key={label} className="gap-4 py-5 shadow-none">
            <CardHeader className="flex flex-row items-center justify-between px-5">
              <CardDescription>{label}</CardDescription>
              <Icon className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent className="px-5">
              <div className="text-3xl font-semibold tabular-nums tracking-tight">
                {value?.toLocaleString() ?? "—"}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <Card className="shadow-none">
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <div className="space-y-1.5">
              <CardTitle>进行中的任务</CardTitle>
              <CardDescription>
                {connectionState === "connected"
                  ? "进度实时更新"
                  : "实时连接正在恢复"}
              </CardDescription>
            </div>
            <Badge variant="outline" className="gap-1.5">
              <span
                className={
                  "size-1.5 rounded-full " +
                  (connectionState === "connected"
                    ? "bg-emerald-500"
                    : "bg-amber-500")
                }
              />
              {connectionState === "connected" ? "已连接" : "连接中"}
            </Badge>
          </CardHeader>
          <CardContent>
            {!status && !error ? (
              <Loading />
            ) : active.length ? (
              <div className="space-y-5">
                {active.map((item) => (
                  <div
                    key={item.gid}
                    className="space-y-3 border-b pb-5 last:border-0"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p
                        className="line-clamp-2 text-sm font-medium break-all"
                        title={item.title}
                      >
                        {item.title || "Gallery " + item.gid}
                      </p>
                      <StatusPill status={item.status || "downloading"} />
                    </div>
                    <GalleryProgressPanel progress={item.progress} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex min-h-52 flex-col items-center justify-center text-center">
                <div className="mb-4 rounded-full bg-muted p-3">
                  <Download className="size-6 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium">暂无正在下载的任务</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  同步收藏夹，或添加画廊链接开始下载。
                </p>
              </div>
            )}
            <Button variant="ghost" className="mt-4 w-full" asChild>
              <Link to="/galleries">
                查看全部任务
                <ArrowRight />
              </Link>
            </Button>
          </CardContent>
        </Card>
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>添加下载</CardTitle>
              <CardDescription>
                粘贴 E-Hentai 或 ExHentai 画廊链接，每行一条。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                aria-label="画廊链接"
                placeholder="https://e-hentai.org/g/…"
                value={urls}
                onChange={(event) => setUrls(event.target.value)}
                className="min-h-28 font-mono text-xs"
              />
              <Button
                className="w-full"
                disabled={adding}
                onClick={() => void add()}
              >
                <Download />
                {adding ? "正在添加…" : "加入下载队列"}
              </Button>
              {results.length > 0 && (
                <ul className="max-h-48 space-y-2 overflow-auto text-xs">
                  {results.map((item, i) => (
                    <li
                      key={i}
                      className={
                        item.success
                          ? "text-emerald-700 dark:text-emerald-400"
                          : "text-destructive"
                      }
                    >
                      <span
                        className="block truncate text-muted-foreground"
                        title={item.url}
                      >
                        {item.url}
                      </span>
                      {item.message}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>同步与服务</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center gap-3">
                <Activity className="size-4 text-muted-foreground" />
                <span className="flex-1">下载服务</span>
                <Badge variant="secondary">
                  {status?.downloader_running ? "运行中" : "未运行"}
                </Badge>
              </div>
              <div className="flex items-center gap-3">
                <Clock3 className="size-4 text-muted-foreground" />
                <span className="flex-1">上次同步</span>
                <span className="text-xs text-muted-foreground">
                  {dateText(status?.last_sync_ts)}
                </span>
              </div>
              {status?.sync_last_error && (
                <ErrorPanel error={new Error(status.sync_last_error)} />
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void mutate();
                  void refreshAccount();
                }}
              >
                <RefreshCw />
                刷新状态
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
