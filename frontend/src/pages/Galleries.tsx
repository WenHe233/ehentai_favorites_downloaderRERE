import { useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  RefreshCw,
  Search,
  Trash2,
  FileText,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ConfirmAction, ErrorPanel, Loading } from "@/components/common";
import StatusPill from "@/components/StatusPill";
import { statusLabels } from "@/lib/status";
import GalleryProgressPanel from "@/components/GalleryProgressPanel";
import { useApi, dateText, errorText } from "@/lib/query";
import {
  useDownloadEventStream,
  type GalleryProgress,
} from "@/lib/download-events";
import api from "@/lib/api";
interface Gallery {
  gid: number;
  token: string;
  title: string;
  status: string;
  filecount: number;
  posted: string | null;
  downloaded_at: string | null;
  favorited_at: string | null;
  error_msg: string | null;
  download_path: string | null;
  parent_gid: string | null;
  requested_quality: string | null;
  resolved_quality: string | null;
  progress: GalleryProgress;
}
interface Page {
  items: Gallery[];
  total: number;
}
interface Logs {
  logs: { time: string; level: string; msg: string }[];
}
const initialWidths = [54, 420, 110, 220, 120, 180, 68];
export default function Galleries() {
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [selected, setSelected] = useState<number[]>([]);
  const [current, setCurrent] = useState<Gallery | null>(null);
  const [busy, setBusy] = useState(false);
  const [widths, setWidths] = useState(initialWidths);
  const drag = useRef<{ index: number; x: number; width: number } | null>(null);
  const query = new URLSearchParams({
    skip: String((page - 1) * size),
    limit: String(size),
    ...(search ? { search } : {}),
    ...(filter !== "all" ? { status: filter } : {}),
  });
  const { data, error, isLoading, mutate } = useApi<Page>(
    "/galleries?" + query,
    15000,
  );
  const {
    data: logs,
    error: logError,
    isLoading: loadingLog,
  } = useApi<Logs>(current ? "/galleries/" + current.gid + "/logs" : null);
  async function refresh() {
    const next = await mutate();
    if (next && page > Math.max(1, Math.ceil(next.total / size)))
      setPage(Math.max(1, Math.ceil(next.total / size)));
  }
  useDownloadEventStream({
    onGalleryProgress: (event) => {
      void mutate(
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((item) =>
                  item.gid === event.gid ? { ...item, ...event } : item,
                ),
              }
            : old,
        { revalidate: false },
      );
    },
    onGalleryStatus: () => void refresh(),
    onSnapshot: () => void refresh(),
    onReconnected: () => void refresh(),
  });
  async function action(
    ids: number[],
    operation: "reset" | "delete" | "files",
  ) {
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        ids.map((id) =>
          operation === "reset"
            ? api.post("/galleries/" + id + "/reset")
            : api.delete(
                "/galleries/" +
                  id +
                  (operation === "files" ? "/with-files" : ""),
              ),
        ),
      );
      const failed = results.filter((result) => result.status === "rejected");
      if (failed.length)
        toast.error(
          failed.length +
            " 项操作失败：" +
            errorText((failed[0] as PromiseRejectedResult).reason),
        );
      else toast.success(operation === "reset" ? "已重新加入队列" : "已删除");
      setSelected([]);
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  const allSelected =
    !!data?.items.length &&
    data.items.every((item) => selected.includes(item.gid));
  const headers = [
    "选择",
    "画廊",
    "状态",
    "下载进度",
    "画质",
    "完成时间",
    "操作",
  ];
  return (
    <div className="space-y-7">
      <div className="flex flex-wrap justify-between gap-4">
        <div>
          <p className="mb-2 text-xs tracking-[.18em] text-muted-foreground">
            LIBRARY
          </p>
          <h1 className="page-heading">下载任务</h1>
          <p className="page-description">
            共 {data?.total ?? "—"} 个任务。重试将使用当前下载设置。
          </p>
        </div>
        <Button variant="outline" onClick={() => void refresh()}>
          <RefreshCw />
          刷新
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <form
          className="relative w-full sm:w-80"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(draft.trim());
            setPage(1);
            setSelected([]);
          }}
        >
          <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
          <Input
            className="pl-9"
            aria-label="搜索任务"
            placeholder="搜索标题或 GID，按回车查询"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </form>
        <Select
          value={filter}
          onValueChange={(value) => {
            setFilter(value);
            setPage(1);
            setSelected([]);
          }}
        >
          <SelectTrigger className="w-36" aria-label="筛选状态">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {Object.entries(statusLabels)
              .filter(([key]) => key !== "cancelled")
              .map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {selected.length ? selected.length + " 项已选" : ""}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={!selected.length || busy}
            onClick={() => void action(selected, "reset")}
          >
            <RefreshCw />
            重试
          </Button>
          <ConfirmAction
            title="删除选中的任务？"
            description="仅删除任务记录，保留已下载文件。"
            action={() => action(selected, "delete")}
          >
            <Button
              variant="outline"
              size="sm"
              disabled={!selected.length || busy}
            >
              <Trash2 />
              删除
            </Button>
          </ConfirmAction>
          <ConfirmAction
            title="清空全部任务记录？"
            description="将取消正在下载的任务并清空列表，保留已下载文件。"
            action={async () => {
              await api.delete("/galleries", { params: { confirm: true } });
              setSelected([]);
              setPage(1);
              await mutate();
              toast.success("任务记录已清空");
            }}
          >
            <Button variant="ghost" size="sm" disabled={!data?.total}>
              清空记录
            </Button>
          </ConfirmAction>
        </div>
      </div>
      {error && <ErrorPanel error={error} retry={() => void refresh()} />}
      <div className="overflow-hidden rounded-xl border bg-card">
        <Table
          style={{
            tableLayout: "fixed",
            minWidth: widths.reduce((a, b) => a + b, 0),
          }}
        >
          <TableHeader>
            <TableRow className="bg-muted/40">
              {headers.map((label, index) => (
                <TableHead
                  key={label}
                  style={{ width: widths[index] }}
                  className="relative h-12 px-4"
                >
                  {index === 0 ? (
                    <Checkbox
                      aria-label="选择本页全部任务"
                      checked={allSelected}
                      onCheckedChange={(checked) =>
                        setSelected(
                          checked
                            ? data?.items.map((item) => item.gid) || []
                            : [],
                        )
                      }
                    />
                  ) : (
                    label
                  )}
                  {index > 0 && index < 6 && (
                    <button
                      aria-label={"调整" + label + "列宽"}
                      className="absolute right-0 top-0 h-full w-2 touch-none cursor-col-resize border-r border-transparent hover:border-primary"
                      onPointerDown={(event) => {
                        drag.current = {
                          index,
                          x: event.clientX,
                          width: widths[index],
                        };
                        event.currentTarget.setPointerCapture(event.pointerId);
                      }}
                      onPointerMove={(event) => {
                        if (drag.current?.index === index) {
                          const width = Math.min(
                            1000,
                            Math.max(
                              90,
                              drag.current.width +
                                event.clientX -
                                drag.current.x,
                            ),
                          );
                          setWidths((current) =>
                            current.map((value, i) =>
                              i === index ? width : value,
                            ),
                          );
                        }
                      }}
                      onPointerUp={() => {
                        drag.current = null;
                      }}
                      onKeyDown={(event) => {
                        if (
                          event.key === "ArrowRight" ||
                          event.key === "ArrowLeft"
                        ) {
                          event.preventDefault();
                          setWidths((current) =>
                            current.map((value, i) =>
                              i === index
                                ? Math.max(
                                    90,
                                    value +
                                      (event.key === "ArrowRight" ? 16 : -16),
                                  )
                                : value,
                            ),
                          );
                        }
                      }}
                    />
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7}>
                  <Loading />
                </TableCell>
              </TableRow>
            ) : !data?.items.length ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="h-60 text-center text-muted-foreground"
                >
                  没有符合条件的任务
                </TableCell>
              </TableRow>
            ) : (
              data.items.map((item) => (
                <TableRow
                  key={item.gid}
                  data-state={
                    selected.includes(item.gid) ? "selected" : undefined
                  }
                >
                  <TableCell className="px-4">
                    <Checkbox
                      aria-label={"选择任务 " + item.gid}
                      checked={selected.includes(item.gid)}
                      onCheckedChange={(checked) =>
                        setSelected((current) =>
                          checked
                            ? [...current, item.gid]
                            : current.filter((id) => id !== item.gid),
                        )
                      }
                    />
                  </TableCell>
                  <TableCell className="whitespace-normal px-4 py-4">
                    <button
                      className="line-clamp-2 text-left text-sm font-medium break-all hover:underline"
                      onClick={() => setCurrent(item)}
                      title={item.title}
                    >
                      {item.title}
                    </button>
                    <div className="mt-1.5 flex gap-3 text-xs text-muted-foreground">
                      <span className="font-mono">#{item.gid}</span>
                      <span>{item.filecount || "—"} 页</span>
                      {item.parent_gid && (
                        <span>更新自 #{item.parent_gid}</span>
                      )}
                    </div>
                    {item.error_msg && (
                      <p
                        className="mt-2 truncate text-xs text-destructive"
                        title={item.error_msg}
                      >
                        {item.error_msg}
                      </p>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusPill status={item.status} />
                  </TableCell>
                  <TableCell className="px-4">
                    <GalleryProgressPanel progress={item.progress} compact />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {item.resolved_quality === "original"
                      ? "原图"
                      : item.resolved_quality === "native"
                        ? "展示图"
                        : item.requested_quality === "original"
                          ? "请求原图"
                          : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {dateText(item.downloaded_at)}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={"任务 " + item.gid + " 操作"}
                        >
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setCurrent(item)}>
                          <FileText />
                          详情与日志
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                          <a
                            className="flex items-center gap-2"
                            target="_blank"
                            rel="noreferrer"
                            href={
                              "https://e-hentai.org/g/" +
                              item.gid +
                              "/" +
                              item.token +
                              "/"
                            }
                          >
                            <ExternalLink className="size-4" />
                            打开画廊
                          </a>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => void action([item.gid], "reset")}
                        >
                          <RefreshCw />
                          重新下载
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => {
                            setSelected([item.gid]);
                            setCurrent(item);
                          }}
                        >
                          <Trash2 />
                          删除选项
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-xs text-muted-foreground">
          <span>
            第 {page} / {Math.max(1, Math.ceil((data?.total || 0) / size))} 页
          </span>
          <div className="flex items-center gap-3">
            <Select
              value={String(size)}
              onValueChange={(value) => {
                setSize(Number(value));
                setPage(1);
                setSelected([]);
              }}
            >
              <SelectTrigger className="h-8 w-28" aria-label="每页数量">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[20, 50, 100, 200].map((value) => (
                  <SelectItem key={value} value={String(value)}>
                    {value} 条 / 页
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="icon"
              aria-label="上一页"
              disabled={page === 1}
              onClick={() => {
                setPage(page - 1);
                setSelected([]);
              }}
            >
              <ChevronLeft />
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="下一页"
              disabled={page * size >= (data?.total || 0)}
              onClick={() => {
                setPage(page + 1);
                setSelected([]);
              }}
            >
              <ChevronRight />
            </Button>
          </div>
        </div>
      </div>
      <Dialog
        open={!!current}
        onOpenChange={(open) => {
          if (!open) setCurrent(null);
        }}
      >
        <DialogContent className="max-h-[85svh] overflow-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="pr-6 leading-7 break-all">
              {current?.title}
            </DialogTitle>
            <DialogDescription>
              任务 #{current?.gid} · {current?.filecount || "—"} 页
            </DialogDescription>
          </DialogHeader>
          {current && (
            <>
              <div className="space-y-3 rounded-lg bg-muted/50 p-4 text-sm">
                <StatusPill status={current.status} />
                <div className="break-all">
                  <span className="text-muted-foreground">输出路径：</span>
                  {current.download_path || "尚未生成文件"}
                </div>
                {current.error_msg && (
                  <p className="text-destructive">{current.error_msg}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void action([current.gid], "reset")}
                  >
                    <RefreshCw />
                    按当前设置重试
                  </Button>
                  <ConfirmAction
                    title="删除任务记录？"
                    description="保留已下载的文件。"
                    action={async () => {
                      await action([current.gid], "delete");
                      setCurrent(null);
                    }}
                  >
                    <Button size="sm" variant="outline">
                      仅删除记录
                    </Button>
                  </ConfirmAction>
                  <ConfirmAction
                    title="删除任务和文件？"
                    description="已下载归档与该任务的断点数据也会删除。"
                    action={async () => {
                      await action([current.gid], "files");
                      setCurrent(null);
                    }}
                  >
                    <Button size="sm" variant="destructive">
                      同时删除文件
                    </Button>
                  </ConfirmAction>
                </div>
              </div>
              <h2 className="mt-2 text-sm font-medium">下载日志</h2>
              {loadingLog ? (
                <Loading />
              ) : logError ? (
                <ErrorPanel error={logError} />
              ) : (
                <div className="space-y-3 text-xs">
                  {logs?.logs.length ? (
                    logs.logs.map((entry, i) => (
                      <div key={i} className="grid gap-1 border-l-2 pl-3">
                        <time className="font-mono text-muted-foreground">
                          {dateText(entry.time)}
                        </time>
                        <p
                          className={
                            "whitespace-pre-wrap break-all " +
                            (entry.level === "error" ? "text-destructive" : "")
                          }
                        >
                          {entry.msg}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="py-6 text-muted-foreground">暂无日志</p>
                  )}
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
