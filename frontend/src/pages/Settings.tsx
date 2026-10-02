import { useState } from "react";
import {
  Save,
  RefreshCw,
  Check,
  ShieldCheck,
  Download,
  Bell,
  Wrench,
  ListFilter,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Loading, ErrorPanel, ConfirmAction } from "@/components/common";
import { useApi, errorText } from "@/lib/query";
import api from "@/lib/api";
type Value = string | number | boolean | number[] | null;
type Values = Record<string, Value>;
interface Field {
  key: string;
  label: string;
  type?:
    "secret" | "number" | "switch" | "select" | "textarea" | "ids" | "date";
  description?: string;
  options?: [string, string][];
  min?: number;
  max?: number;
}
const account: Field[] = [
  {
    key: "eh_domain",
    label: "站点",
    type: "select",
    options: [
      ["e-hentai.org", "E-Hentai"],
      ["exhentai.org", "ExHentai"],
    ],
  },
  { key: "ipb_member_id", label: "IPB Member ID", type: "secret" },
  { key: "ipb_pass_hash", label: "IPB Pass Hash", type: "secret" },
  {
    key: "igneous",
    label: "Igneous",
    type: "secret",
    description: "ExHentai 使用的 Cookie。",
  },
  {
    key: "cookie_auto_refresh",
    label: "自动刷新 Igneous",
    type: "switch",
    description: "会话失效时尝试使用已保存的账号 Cookie 刷新。",
  },
];
const sync: Field[] = [
  {
    key: "auto_sync",
    label: "自动同步收藏夹",
    type: "switch",
    description: "按 config.yaml 中的同步间隔检查更新。",
  },
  {
    key: "fav_date_timezone",
    label: "收藏时间时区",
    type: "select",
    options: [
      ["off", "不按日期筛选"],
      ["site", "站点时间（UTC）"],
      ["server", "服务器本地时间"],
    ],
  },
  {
    key: "fav_oldest_date",
    label: "仅下载此时之后的收藏",
    type: "date",
    description: "启用日期筛选后生效。修改规则后，可重置同步进度重新扫描。",
  },
];
const downloads: Field[] = [
  {
    key: "download_mode",
    label: "下载模式",
    type: "select",
    options: [
      ["archive", "归档下载"],
      ["native_crawl", "原生图片抓取"],
    ],
  },
  {
    key: "archive_quality",
    label: "画质偏好",
    type: "select",
    options: [
      ["original", "原图"],
      ["native", "展示图"],
    ],
    description: "原生抓取无法取得原图时会使用展示图，结果中显示实际画质。",
  },
  {
    key: "max_concurrent_downloads",
    label: "并发下载数",
    type: "number",
    min: 1,
    max: 32,
    description: "归档模式控制画廊数量；原生模式控制同一画廊内的图片数量。",
  },
  {
    key: "max_retries",
    label: "失败重试次数",
    type: "number",
    min: 0,
    max: 20,
  },
  {
    key: "proxy_url",
    label: "网络代理",
    description: "例如 http://127.0.0.1:7890；留空表示不使用代理。",
  },
  {
    key: "output_template",
    label: "输出路径模板",
    description:
      "可用字段：{gid}、{title}、{jpn_title}、{category}、{uploader}、{filecount}、{quality}、{parent_gid}、{downloaded_at}、{favorited_at}、{fav}。",
  },
  {
    key: "conflict_strategy",
    label: "文件冲突处理",
    type: "select",
    options: [
      ["rename", "自动编号"],
      ["overwrite", "覆盖同名文件"],
    ],
  },
  {
    key: "truncate_filenames",
    label: "截断过长的文件名",
    type: "switch",
    description:
      "保留数据库中的完整标题，仅缩短输出文件名。修改后重试已有失败任务也会生效。",
  },
  {
    key: "filename_max_length",
    label: "文件名最大长度",
    type: "number",
    min: 16,
    max: 240,
    description: "程序还会根据当前文件系统与完整路径长度进一步缩短文件名。",
  },
];
const telegram: Field[] = [
  { key: "telegram_bot_token", label: "Bot Token", type: "secret" },
  {
    key: "allowed_telegram_ids",
    label: "允许使用 Bot 的用户 ID",
    type: "ids",
    description: "逗号或换行分隔；留空时禁止所有用户。",
  },
  {
    key: "telegram_notifications_enabled",
    label: "启用主动提醒",
    type: "switch",
  },
  {
    key: "telegram_notification_recipients",
    label: "提醒接收人或群组 ID",
    type: "ids",
    description: "逗号或换行分隔；群组 ID 可为负数。留空时使用允许的用户 ID。",
  },
  {
    key: "telegram_notify_download_completed",
    label: "下载完成提醒",
    type: "switch",
  },
  {
    key: "telegram_notify_download_failed",
    label: "下载失败提醒",
    type: "switch",
  },
  {
    key: "telegram_notify_download_partial",
    label: "部分完成提醒",
    type: "switch",
  },
  {
    key: "telegram_notify_sync_completed",
    label: "同步完成摘要",
    type: "switch",
  },
  { key: "telegram_notify_sync_failed", label: "同步失败提醒", type: "switch" },
  {
    key: "telegram_notification_batch_window_seconds",
    label: "提醒聚合窗口（秒）",
    type: "number",
    min: 0,
    max: 86400,
  },
  {
    key: "telegram_notification_quiet_hours_enabled",
    label: "启用静默时段",
    type: "switch",
  },
  {
    key: "telegram_notification_quiet_hours_start",
    label: "静默开始时间",
    description: "24 小时制，例如 23:00。",
  },
  {
    key: "telegram_notification_quiet_hours_end",
    label: "静默结束时间",
    description: "例如 08:00，支持跨午夜。",
  },
];
const fields = [...account, ...sync, ...downloads, ...telegram];
function SettingsForm({
  initial,
  reload,
}: {
  initial: Values;
  reload: () => Promise<Values | undefined>;
}) {
  const [values, setValues] = useState<Values>(initial);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState("account");
  const {
    data: legacy,
    error: legacyError,
    mutate: reloadLegacy,
  } = useApi<{
    legacy_app_config_count: number;
    temp_cookies_exists: boolean;
    downloads_zip_exists: boolean;
  }>("/maintenance/legacy-state");
  const update = (key: string, value: Value) => {
    setValues((current) => ({ ...current, [key]: value }));
    setDirty(true);
  };
  async function save() {
    setSaving(true);
    try {
      const payload: Values = {};
      for (const field of fields)
        payload[field.key] = values[field.key] ?? null;
      payload.monitored_favcats = values.monitored_favcats;
      for (const key of [
        "allowed_telegram_ids",
        "telegram_notification_recipients",
      ]) {
        const raw = payload[key];
        const ids = Array.isArray(raw)
          ? raw
          : String(raw ?? "")
              .split(/[,，\s]+/)
              .filter(Boolean)
              .map(Number);
        if (
          ids.some(
            (id) =>
              !Number.isSafeInteger(id) ||
              id === 0 ||
              (key === "allowed_telegram_ids" && id < 0),
          )
        )
          throw new Error("请输入有效的 Telegram ID");
        payload[key] = ids;
      }
      if (payload.fav_date_timezone === "off") payload.fav_date_timezone = null;
      payload.fav_oldest_date = payload.fav_oldest_date
        ? String(payload.fav_oldest_date).replace("T", " ")
        : null;
      if (!payload.proxy_url) payload.proxy_url = null;
      await api.post("/settings", payload);
      const next = await reload();
      if (next) setValues(next);
      setDirty(false);
      toast.success("设置已保存");
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setSaving(false);
    }
  }
  function render(field: Field) {
    const value = values[field.key];
    const configured = values[field.key + "_configured"];
    const control =
      field.type === "switch" ? (
        <Switch
          id={field.key}
          checked={Boolean(value)}
          onCheckedChange={(checked) => update(field.key, checked)}
        />
      ) : field.type === "select" ? (
        <Select
          value={String(value ?? "off")}
          onValueChange={(value) => update(field.key, value)}
        >
          <SelectTrigger id={field.key} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options?.map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.type === "ids" || field.type === "textarea" ? (
        <Textarea
          id={field.key}
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(event) => update(field.key, event.target.value)}
        />
      ) : (
        <div className="flex gap-2">
          <Input
            id={field.key}
            type={
              field.type === "secret"
                ? "password"
                : field.type === "number"
                  ? "number"
                  : field.type === "date"
                    ? "datetime-local"
                    : "text"
            }
            autoComplete={field.type === "secret" ? "new-password" : undefined}
            min={field.min}
            max={field.max}
            step={field.type === "number" ? 1 : undefined}
            value={
              field.type === "date"
                ? String(value ?? "").replace(" ", "T")
                : String(value ?? "")
            }
            placeholder={
              field.type === "secret"
                ? value === null
                  ? "保存后清除"
                  : configured
                    ? "已配置，留空保留"
                    : "尚未配置"
                : undefined
            }
            onChange={(event) =>
              update(
                field.key,
                field.type === "number"
                  ? event.target.value === ""
                    ? null
                    : Number(event.target.value)
                  : event.target.value,
              )
            }
          />
          {field.type === "secret" && !!configured && (
            <Button
              type="button"
              variant="outline"
              onClick={() => update(field.key, null)}
            >
              清除
            </Button>
          )}
        </div>
      );
    return (
      <div
        key={field.key}
        className={
          field.type === "switch"
            ? "flex items-center justify-between gap-6 rounded-lg border p-4"
            : "field"
        }
      >
        <div className="space-y-1.5">
          <Label htmlFor={field.key}>
            {field.label}
            {field.type === "secret" && !!configured && (
              <Check className="size-3.5 text-emerald-600" />
            )}
          </Label>
          {field.type === "switch" && field.description && (
            <p className="text-xs leading-5 text-muted-foreground">
              {field.description}
            </p>
          )}
        </div>
        {control}
        {field.type !== "switch" && field.description && (
          <p className="text-xs leading-5 text-muted-foreground">
            {field.description}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-7 pb-16">
      <div>
        <p className="mb-2 text-xs tracking-[.18em] text-muted-foreground">
          PREFERENCES
        </p>
        <h1 className="page-heading">设置</h1>
        <p className="page-description">
          管理账号、下载策略和通知。保存后的设置用于后续任务与重试。
        </p>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-6 h-auto flex-wrap">
          {[
            { value: "account", label: "账号", icon: ShieldCheck },
            { value: "sync", label: "同步", icon: ListFilter },
            { value: "downloads", label: "下载", icon: Download },
            { value: "telegram", label: "通知", icon: Bell },
            { value: "maintenance", label: "维护", icon: Wrench },
          ].map(({ value, label, icon: Icon }) => (
            <TabsTrigger key={value} value={value} className="gap-2 px-5 py-2">
              <Icon className="size-4" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        {[
          {
            value: "account",
            title: "账号与站点",
            description: "Cookie 只保存在后端配置中，页面不会读取已保存的值。",
            fields: account,
          },
          {
            value: "sync",
            title: "收藏夹同步",
            description: "选择需要同步的收藏夹与时间范围。",
            fields: sync,
          },
          {
            value: "downloads",
            title: "下载与文件命名",
            description: "命名错误的任务可以在修改设置后直接重试。",
            fields: downloads,
          },
          {
            value: "telegram",
            title: "Telegram 与提醒",
            description: "Bot 控制、完成通知与静默时段。",
            fields: telegram,
          },
        ].map((section) => (
          <TabsContent key={section.value} value={section.value}>
            <Card className="max-w-3xl shadow-none">
              <CardHeader>
                <CardTitle>{section.title}</CardTitle>
                <CardDescription>{section.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  className="space-y-6"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void save();
                  }}
                >
                  {section.fields.map(render)}
                  {section.value === "account" && (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={refreshing}
                      onClick={async () => {
                        setRefreshing(true);
                        try {
                          await api.post(
                            "/auth/eh-refresh-igneous",
                            {},
                            { timeout: 45000 },
                          );
                          const next = await reload();
                          setValues((current) => ({
                            ...current,
                            igneous_configured:
                              next?.igneous_configured ?? true,
                          }));
                          toast.success("Igneous 已刷新");
                        } catch (error) {
                          toast.error(errorText(error));
                        } finally {
                          setRefreshing(false);
                        }
                      }}
                    >
                      <RefreshCw className={refreshing ? "animate-spin" : ""} />
                      {refreshing ? "正在刷新…" : "立即刷新 Igneous"}
                    </Button>
                  )}
                  {section.value === "sync" && (
                    <div className="space-y-4">
                      <Label>监控的收藏夹</Label>
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                        {Array.from({ length: 10 }, (_, cat) => (
                          <label
                            key={cat}
                            className="flex items-center gap-2 rounded-md border p-3 text-sm"
                          >
                            <Checkbox
                              checked={
                                Array.isArray(values.monitored_favcats) &&
                                values.monitored_favcats.includes(cat)
                              }
                              onCheckedChange={(checked) => {
                                const current = Array.isArray(
                                  values.monitored_favcats,
                                )
                                  ? values.monitored_favcats
                                  : [];
                                update(
                                  "monitored_favcats",
                                  checked
                                    ? [...current, cat].sort()
                                    : current.filter((item) => item !== cat),
                                );
                              }}
                            />
                            收藏夹 {cat}
                          </label>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        不选择任何分类时不会同步收藏夹。
                      </p>
                    </div>
                  )}
                  <Button type="submit" className="sr-only">
                    保存设置
                  </Button>
                </form>
              </CardContent>
            </Card>
          </TabsContent>
        ))}
        <TabsContent value="maintenance">
          <div className="max-w-3xl space-y-6">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>同步进度</CardTitle>
                <CardDescription>
                  修改收藏夹或日期筛选后，可从头重新扫描；已有任务保留。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ConfirmAction
                  title="重置同步进度？"
                  description="清除增量游标和失败重试队列，下次同步重新扫描。"
                  action={async () => {
                    await api.post("/action/reset-sync-state");
                    toast.success("同步进度已重置");
                  }}
                >
                  <Button variant="outline">
                    <RefreshCw />
                    重置同步进度
                  </Button>
                </ConfirmAction>
              </CardContent>
            </Card>
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>旧版残留</CardTitle>
                <CardDescription>
                  检查数据库中的旧配置、临时 Cookie 和旧下载包。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {legacyError && <ErrorPanel error={legacyError} />}
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">
                    旧配置 {legacy?.legacy_app_config_count ?? "—"} 项
                  </Badge>
                  <Badge variant="secondary">
                    临时 Cookie {legacy?.temp_cookies_exists ? "存在" : "无"}
                  </Badge>
                  <Badge variant="secondary">
                    旧下载包 {legacy?.downloads_zip_exists ? "存在" : "无"}
                  </Badge>
                </div>
                <ConfirmAction
                  title="清理旧版残留？"
                  description="删除上方列出的旧配置、临时 Cookie 和旧下载包，保留当前配置与下载任务。"
                  action={async () => {
                    await api.post("/maintenance/cleanup", {
                      cleanup_app_config: true,
                      cleanup_temp_cookies: true,
                      cleanup_downloads_zip: true,
                    });
                    await reloadLegacy();
                    toast.success("已清理旧版残留");
                  }}
                >
                  <Button
                    variant="outline"
                    disabled={
                      !legacy?.legacy_app_config_count &&
                      !legacy?.temp_cookies_exists &&
                      !legacy?.downloads_zip_exists
                    }
                  >
                    <Wrench />
                    清理残留
                  </Button>
                </ConfirmAction>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
      {tab !== "maintenance" && (
        <div className="fixed inset-x-0 bottom-0 z-10 flex items-center justify-end gap-4 border-t bg-background/95 px-6 py-4 backdrop-blur md:left-56 md:px-10">
          <span className="text-xs text-muted-foreground">
            {dirty ? "有未保存的修改" : "设置已同步"}
          </span>
          <Button disabled={saving || !dirty} onClick={() => void save()}>
            <Save />
            {saving ? "正在保存…" : "保存设置"}
          </Button>
        </div>
      )}
    </div>
  );
}
export default function Settings() {
  const { data, error, mutate } = useApi<Values>("/settings");
  if (error) return <ErrorPanel error={error} retry={() => void mutate()} />;
  if (!data) return <Loading />;
  return <SettingsForm initial={data} reload={() => mutate()} />;
}
