import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert,
    Button,
    Card,
    Checkbox,
    DatePicker,
    Form,
    Input,
    InputNumber,
    Popconfirm,
    Select,
    Spin,
    Switch,
    Typography,
    message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import ApiConnectionSettings from '../components/ApiConnectionSettings';
import api, { isCustomApiBaseUrl, useApiBaseUrl } from '../lib/api';

const secretFields = ['ipb_member_id', 'ipb_pass_hash', 'igneous', 'telegram_bot_token'] as const;
type SecretField = (typeof secretFields)[number];

interface SettingsResponse {
    ipb_member_id: string;
    ipb_pass_hash: string;
    igneous: string;
    cookie_auto_refresh: boolean;
    eh_domain: string;
    download_mode: string;
    archive_quality: string;
    telegram_bot_token: string;
    allowed_telegram_ids: number[];
    telegram_notifications_enabled: boolean;
    telegram_notification_recipients: number[];
    telegram_notify_download_completed: boolean;
    telegram_notify_download_failed: boolean;
    telegram_notify_download_partial: boolean;
    telegram_notify_sync_completed: boolean;
    telegram_notify_sync_failed: boolean;
    telegram_notification_batch_window_seconds: number;
    telegram_notification_quiet_hours_enabled: boolean;
    telegram_notification_quiet_hours_start: string;
    telegram_notification_quiet_hours_end: string;
    proxy_url: string | null;
    monitored_favcats: number[];
    fav_oldest_date: string | null;
    fav_date_timezone: string | null;
    auto_sync: boolean;
    max_concurrent_downloads: number;
    max_retries: number;
    output_template: string;
    conflict_strategy: string;
    truncate_filenames: boolean;
    filename_max_length: number;
    ipb_member_id_configured?: boolean;
    ipb_pass_hash_configured?: boolean;
    igneous_configured?: boolean;
    telegram_bot_token_configured?: boolean;
}

interface LegacyStateResponse {
    legacy_app_config_keys: string[];
    legacy_app_config_count: number;
    temp_cookies_exists: boolean;
    temp_cookies_path: string;
    downloads_zip_exists: boolean;
    downloads_zip_path: string;
}

interface SettingsFormValues {
    ipb_member_id?: string;
    ipb_pass_hash?: string;
    igneous?: string;
    cookie_auto_refresh?: boolean;
    eh_domain?: string;
    download_mode?: string;
    archive_quality?: string;
    telegram_bot_token?: string;
    allowed_telegram_ids?: Array<string | number>;
    telegram_notifications_enabled?: boolean;
    telegram_notification_recipients?: Array<string | number>;
    telegram_notify_download_completed?: boolean;
    telegram_notify_download_failed?: boolean;
    telegram_notify_download_partial?: boolean;
    telegram_notify_sync_completed?: boolean;
    telegram_notify_sync_failed?: boolean;
    telegram_notification_batch_window_seconds?: number;
    telegram_notification_quiet_hours_enabled?: boolean;
    telegram_notification_quiet_hours_start?: string;
    telegram_notification_quiet_hours_end?: string;
    proxy_url?: string | null;
    monitored_favcats?: number[];
    fav_oldest_date?: Dayjs | null;
    fav_date_timezone?: string | null;
    auto_sync?: boolean;
    max_concurrent_downloads?: number;
    max_retries?: number;
    output_template?: string;
    conflict_strategy?: string;
    truncate_filenames?: boolean;
    filename_max_length?: number;
}

const allowedTemplateFields = new Set([
    'gid',
    'title',
    'jpn_title',
    'category',
    'uploader',
    'filecount',
    'quality',
    'parent_gid',
    'downloaded_at',
    'favorited_at',
    'fav',
]);
const datetimeTemplateFields = new Set(['downloaded_at', 'favorited_at']);
const hhmmPattern = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

const validateOutputTemplate = (template: string) => {
    const trimmed = template.trim();
    if (!trimmed) {
        return '输出路径模板不能为空';
    }
    if (/[\\/]\s*$/.test(trimmed)) {
        return '输出路径模板必须包含文件名，不能只填写目录';
    }

    const segments = trimmed.replaceAll('\\', '/').split('/');
    if (segments.includes('..')) {
        return '输出路径模板不允许使用 .. 向上跳目录';
    }

    let cursor = 0;
    while (cursor < trimmed.length) {
        const open = trimmed.indexOf('{', cursor);
        if (open === -1) {
            break;
        }
        const close = trimmed.indexOf('}', open + 1);
        if (close === -1) {
            return '输出路径模板存在未闭合的 {';
        }
        const rawField = trimmed.slice(open + 1, close).trim();
        if (!rawField) {
            return '输出路径模板中存在空占位符';
        }
        const [fieldName, ...formatRest] = rawField.split(':');
        if (!allowedTemplateFields.has(fieldName)) {
            return `不支持的占位符 {${fieldName}}`;
        }
        if (formatRest.length > 0 && !datetimeTemplateFields.has(fieldName)) {
            return `只有时间字段支持格式化：{${rawField}}`;
        }
        cursor = close + 1;
    }

    const extraClose = trimmed.indexOf('}');
    const extraOpen = trimmed.indexOf('{');
    if (extraClose !== -1 && (extraOpen === -1 || extraClose < extraOpen)) {
        return '输出路径模板存在多余的 }';
    }

    return null;
};

const validateQuietHourTime = (value?: string) => {
    const trimmed = (value || '').trim();
    if (!trimmed) {
        return '时间不能为空';
    }
    if (!hhmmPattern.test(trimmed)) {
        return '时间必须是 HH:mm 格式';
    }
    return null;
};

const Settings: React.FC = () => {
    const apiBaseUrl = useApiBaseUrl();
    const [form] = Form.useForm<SettingsFormValues>();
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [legacyState, setLegacyState] = useState<LegacyStateResponse | null>(null);
    const [maintenanceLoading, setMaintenanceLoading] = useState(false);
    const [configuredSecrets, setConfiguredSecrets] = useState<Record<SecretField, boolean>>({
        ipb_member_id: false,
        ipb_pass_hash: false,
        igneous: false,
        telegram_bot_token: false,
    });

    const fetchLegacyState = useCallback(async () => {
        try {
            const response = await api.get<LegacyStateResponse>('/maintenance/legacy-state');
            setLegacyState(response.data);
        } catch (error) {
            console.error(error);
        }
    }, []);

    const fetchSettings = useCallback(async () => {
        setLoading(true);

        try {
            const response = await api.get<SettingsResponse>('/settings');
            const data = response.data;
            const secretState: Record<SecretField, boolean> = {
                ipb_member_id: false,
                ipb_pass_hash: false,
                igneous: false,
                telegram_bot_token: false,
            };

            secretFields.forEach((field) => {
                secretState[field] = Boolean(data[`${field}_configured` as keyof SettingsResponse]);
            });

            setConfiguredSecrets(secretState);
            form.setFieldsValue({
                ...data,
                ipb_member_id: '',
                ipb_pass_hash: '',
                igneous: '',
                telegram_bot_token: '',
                allowed_telegram_ids: data.allowed_telegram_ids?.map((value) => String(value)) || [],
                telegram_notification_recipients:
                    data.telegram_notification_recipients?.map((value) => String(value)) || [],
                fav_oldest_date: data.fav_oldest_date ? dayjs(data.fav_oldest_date) : null,
            });
        } catch (error) {
            console.error(error);
            message.error('加载设置失败');
        } finally {
            setLoading(false);
        }
    }, [form]);

    useEffect(() => {
        void fetchSettings();
        void fetchLegacyState();
    }, [fetchLegacyState, fetchSettings]);

    const onFinish = async (values: SettingsFormValues) => {
        setSaving(true);

        try {
            const templateError = validateOutputTemplate(values.output_template || '');
            if (templateError) {
                message.error(templateError);
                return;
            }

            const payload: Record<string, unknown> = { ...values };

            payload.fav_oldest_date = values.fav_oldest_date
                ? values.fav_oldest_date.format('YYYY-MM-DD HH:mm')
                : null;

            payload.allowed_telegram_ids = (values.allowed_telegram_ids || [])
                .map((value) => Number(value))
                .filter((value) => Number.isInteger(value) && value > 0);
            payload.telegram_notification_recipients = (values.telegram_notification_recipients || [])
                .map((value) => Number(value))
                .filter((value) => Number.isInteger(value) && value > 0);
            payload.telegram_notification_quiet_hours_start = values.telegram_notification_quiet_hours_start?.trim() || '23:00';
            payload.telegram_notification_quiet_hours_end = values.telegram_notification_quiet_hours_end?.trim() || '08:00';

            const quietHoursEnabled = Boolean(values.telegram_notification_quiet_hours_enabled);
            if (quietHoursEnabled) {
                const startError = validateQuietHourTime(payload.telegram_notification_quiet_hours_start as string);
                const endError = validateQuietHourTime(payload.telegram_notification_quiet_hours_end as string);
                if (startError || endError) {
                    message.error(startError || endError || '静默时段格式不正确');
                    return;
                }
            }

            secretFields.forEach((field) => {
                const rawValue = values[field];
                if (!rawValue?.trim()) {
                    delete payload[field];
                }
            });

            await api.post('/settings', payload);
            message.success('设置已保存 (服务热重载生效中)');
            await fetchSettings();
        } catch (error) {
            console.error(error);
            const detail =
                typeof error === 'object' &&
                error !== null &&
                'response' in error &&
                typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
                    ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
                    : null;
            message.error(detail || '保存失败');
        } finally {
            setSaving(false);
        }
    };

    const handleResetSyncState = async () => {
        try {
            await api.post('/action/reset-sync-state');
            message.success('同步状态已重置，下次同步会从当前筛选条件重新扫描');
        } catch (error) {
            console.error(error);
            message.error('重置失败');
        }
    };

    const handleCleanupLegacy = async (payload: {
        cleanup_app_config?: boolean;
        cleanup_temp_cookies?: boolean;
        cleanup_downloads_zip?: boolean;
    }) => {
        setMaintenanceLoading(true);
        try {
            await api.post('/maintenance/cleanup', payload);
            message.success('旧残留已处理');
            await fetchLegacyState();
        } catch (error) {
            console.error(error);
            message.error('清理失败');
        } finally {
            setMaintenanceLoading(false);
        }
    };

    const favcatOptions = [
        { label: 'Fav 0', value: 0 },
        { label: 'Fav 1', value: 1 },
        { label: 'Fav 2', value: 2 },
        { label: 'Fav 3', value: 3 },
        { label: 'Fav 4', value: 4 },
        { label: 'Fav 5', value: 5 },
        { label: 'Fav 6', value: 6 },
        { label: 'Fav 7', value: 7 },
        { label: 'Fav 8', value: 8 },
        { label: 'Fav 9', value: 9 },
    ];

    if (loading) {
        return <Spin size="large" className="flex justify-center mt-10" />;
    }

    return (
        <div className="space-y-6">
            <section className="console-hero">
                <div>
                    <div className="console-kicker">System Settings</div>
                    <h1 className="console-title">系统设置</h1>
                    <p className="console-description">
                        在这里配置站点登录信息、同步范围、下载方式、通知参数和维护操作。
                    </p>
                </div>
                <div className="console-actions">
                    <div className="console-note">
                        保存后，新的同步任务和下载任务会按照最新设置执行。
                    </div>
                </div>
            </section>

            <Form layout="vertical" form={form} onFinish={onFinish} className="space-y-6">
                <div className="settings-grid">
                    <Card title="连接与部署" bordered={false} className="console-card settings-card settings-grid__full">
                        <div className="api-settings-card">
                            <div className="api-settings-card__summary">
                                <div className="api-settings-card__label">当前后端地址</div>
                                <code>{apiBaseUrl}</code>
                                <Typography.Paragraph className="settings-card__hint">
                                    默认情况下，前端会通过同源 <code>/api/v1</code> 访问后端。
                                    如果前后端不在同一地址，可以在这里手动改成新的服务器地址。
                                    当前来源：{isCustomApiBaseUrl() ? '已自定义' : '默认配置'}。
                                </Typography.Paragraph>
                            </div>
                            <div className="api-settings-card__actions">
                                <ApiConnectionSettings
                                    buttonText="修改后端地址"
                                    buttonType="primary"
                                    onSaved={() => {
                                        void fetchSettings();
                                    }}
                                />
                            </div>
                        </div>
                    </Card>

                    <Card title="E-Hentai 账户 (Cookies)" bordered={false} className="console-card settings-card">
                        <Form.Item label="站点域名" name="eh_domain" tooltip="ExHentai 需要有效的 igneous cookie">
                            <Select>
                                <Select.Option value="e-hentai.org">e-hentai.org (普通站)</Select.Option>
                                <Select.Option value="exhentai.org">exhentai.org (里站)</Select.Option>
                            </Select>
                        </Form.Item>
                        <Form.Item label="IPB Member ID" name="ipb_member_id">
                            <Input placeholder={configuredSecrets.ipb_member_id ? '已保存，留空保持不变' : 'Cookie value'} />
                        </Form.Item>
                        <Form.Item label="IPB Pass Hash" name="ipb_pass_hash">
                            <Input.Password
                                placeholder={configuredSecrets.ipb_pass_hash ? '已保存，留空保持不变' : 'Cookie value'}
                            />
                        </Form.Item>
                        <Form.Item label="Igneous" name="igneous" tooltip="ExHentai 必需">
                            <Input.Password placeholder={configuredSecrets.igneous ? '已保存，留空保持不变' : 'Cookie value'} />
                        </Form.Item>
                        <Form.Item label="自动刷新 igneous" name="cookie_auto_refresh" valuePropName="checked" tooltip="当 igneous 过期时自动刷新，需要 ipb_member_id 和 ipb_pass_hash">
                            <Switch />
                        </Form.Item>
                        <Form.Item label="手动刷新 igneous">
                            <Button
                                onClick={async () => {
                                    try {
                                        const resp = await api.post('/api/v1/auth/eh-refresh-igneous');
                                        message.success(`igneous 刷新成功: ${resp.data.igneous}`);
                                    } catch (err: any) {
                                        message.error(err?.response?.data?.detail || '刷新失败');
                                    }
                                }}
                            >
                                刷新 igneous
                            </Button>
                        </Form.Item>
                        <Typography.Paragraph className="settings-card__hint">
                            敏感字段不会回显原值。留空表示保持当前配置不变。
                        </Typography.Paragraph>
                    </Card>

                    <Card title="监控与筛选" bordered={false} className="console-card settings-card">
                        <Form.Item label="监控的收藏夹 (Favcats)" name="monitored_favcats">
                            <Checkbox.Group options={favcatOptions} />
                        </Form.Item>
                        <Form.Item label="自动同步" name="auto_sync" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item
                            label="时区"
                            name="fav_date_timezone"
                            tooltip="站点时区为 GMT+0，如果你将输入本地时间请选择服务器时区"
                        >
                            <Select placeholder="选择时区后可设置日期过滤" allowClear>
                                <Select.Option value="site">站点时区 (GMT+0)</Select.Option>
                                <Select.Option value="server">
                                    服务器时区 (GMT{-(new Date().getTimezoneOffset() / 60) >= 0 ? '+' : ''}
                                    {-(new Date().getTimezoneOffset() / 60)})
                                </Select.Option>
                            </Select>
                        </Form.Item>
                        <Form.Item
                            noStyle
                            shouldUpdate={(prevValues, currentValues) =>
                                prevValues.fav_date_timezone !== currentValues.fav_date_timezone
                            }
                        >
                            {({ getFieldValue }) => {
                                const hasTimezone = getFieldValue('fav_date_timezone');
                                if (!hasTimezone && getFieldValue('fav_oldest_date')) {
                                    window.setTimeout(() => form.setFieldValue('fav_oldest_date', null), 0);
                                }

                                return (
                                    <Form.Item label="仅下载此时之后的收藏" name="fav_oldest_date">
                                        <DatePicker
                                            showTime
                                            format="YYYY-MM-DD HH:mm"
                                            style={{ width: '100%' }}
                                            placeholder={hasTimezone ? '选择日期时间' : '请先选择时区'}
                                            disabled={!hasTimezone}
                                        />
                                    </Form.Item>
                                );
                            }}
                        </Form.Item>
                        <div className="pt-2">
                            <Popconfirm
                                title="重置同步状态？"
                                description="会清空增量游标和失败重试队列，下次同步将重新扫描最近收藏。"
                                onConfirm={handleResetSyncState}
                                okText="重置"
                                cancelText="取消"
                            >
                                <Button danger>重置同步状态</Button>
                            </Popconfirm>
                        </div>
                    </Card>

                    <Card title="下载选项" bordered={false} className="console-card settings-card">
                        <Form.Item label="下载模式" name="download_mode">
                            <Select>
                                <Select.Option value="archive">Archive (归档模式 - 推荐)</Select.Option>
                                <Select.Option value="native_crawl">Native Crawler (原生爬虫 - 支持取消)</Select.Option>
                            </Select>
                        </Form.Item>
                        <Form.Item
                            label="画质偏好"
                            name="archive_quality"
                            tooltip="Archive 模式下 native 对应站点的压缩归档；Native Crawler 模式下 native 表示当前展示图"
                        >
                            <Select>
                                <Select.Option value="original">Original (原图)</Select.Option>
                                <Select.Option value="native">Native (当前展示图 / 站点压缩归档)</Select.Option>
                            </Select>
                        </Form.Item>
                        <Form.Item
                            label="并发下载数"
                            name="max_concurrent_downloads"
                            tooltip="归档模式：同时下载多个画廊；原生爬虫：同时下载多张图片"
                        >
                            <InputNumber min={1} max={10} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item label="重试次数" name="max_retries" tooltip="下载失败时的最大重试次数">
                            <InputNumber min={0} max={10} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item label="网络代理" name="proxy_url" tooltip="例如 http://127.0.0.1:7890">
                            <Input placeholder="http://127.0.0.1:7890" />
                        </Form.Item>
                        <Form.Item
                            label="输出路径模板"
                            name="output_template"
                            tooltip="相对路径以 backend 目录为基准。支持目录和文件名一起自定义。"
                            rules={[
                                {
                                    validator: async (_, value) => {
                                        const error = validateOutputTemplate(value || '');
                                        if (error) {
                                            throw new Error(error);
                                        }
                                    },
                                },
                            ]}
                        >
                            <Input.TextArea
                                rows={3}
                                placeholder="./downloads/[{gid}] {title}.zip"
                                autoSize={{ minRows: 3, maxRows: 5 }}
                            />
                        </Form.Item>
                        <Form.Item label="冲突处理" name="conflict_strategy">
                            <Select>
                                <Select.Option value="rename">重命名 (file_1.zip)</Select.Option>
                                <Select.Option value="overwrite">覆盖已有文件</Select.Option>
                            </Select>
                        </Form.Item>
                        <Form.Item label="长文件名截断" name="truncate_filenames" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item
                            label="文件名最大长度"
                            name="filename_max_length"
                            tooltip="仅对最终文件名生效，不含上级目录。Windows 默认 160，Linux/macOS 默认 220。"
                        >
                            <InputNumber min={16} max={240} style={{ width: '100%' }} />
                        </Form.Item>
                        <Typography.Paragraph className="settings-card__hint">
                            模板可用字段：
                            {' {gid}、{title}、{jpn_title}、{category}、{uploader}、{filecount}、{quality}、{parent_gid}、'}
                            {'{downloaded_at:%Y-%m-%d}、{favorited_at:%Y-%m-%d}、{fav}。'}
                            程序实际打包为 ZIP 容器，建议扩展名使用 `.zip` 或 `.cbz`。
                        </Typography.Paragraph>
                    </Card>

                    <Card title="Telegram Bot" bordered={false} className="console-card settings-card">
                        <Form.Item label="Bot Token" name="telegram_bot_token" tooltip="从 @BotFather 获取">
                            <Input.Password
                                placeholder={configuredSecrets.telegram_bot_token ? '已保存，留空保持不变' : 'Token'}
                            />
                        </Form.Item>
                        <Form.Item
                            label="允许的 Telegram 用户 ID"
                            name="allowed_telegram_ids"
                            tooltip="留空时拒绝所有用户，可直接输入多个数字"
                        >
                            <Select
                                mode="tags"
                                tokenSeparators={[',', ' ']}
                                placeholder="例如 123456789"
                                open={false}
                            />
                        </Form.Item>
                        <Form.Item label="启用主动提醒" name="telegram_notifications_enabled" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item
                            label="提醒接收人"
                            name="telegram_notification_recipients"
                            tooltip="留空时会回退到上面的允许 ID 列表"
                        >
                            <Select
                                mode="tags"
                                tokenSeparators={[',', ' ']}
                                placeholder="例如 123456789"
                                open={false}
                            />
                        </Form.Item>
                        <Form.Item label="下载完成提醒" name="telegram_notify_download_completed" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item label="下载失败提醒" name="telegram_notify_download_failed" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item label="部分完成提醒" name="telegram_notify_download_partial" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item label="同步完成摘要" name="telegram_notify_sync_completed" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item label="同步失败提醒" name="telegram_notify_sync_failed" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        <Form.Item
                            label="聚合窗口（秒）"
                            name="telegram_notification_batch_window_seconds"
                            tooltip="大于 0 时，窗口内的多条提醒会合并成一条摘要"
                        >
                            <InputNumber min={0} max={3600} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item
                            label="启用静默时段"
                            name="telegram_notification_quiet_hours_enabled"
                            valuePropName="checked"
                            tooltip="按服务器本地时间判断。静默期间的提醒会缓存，结束后汇总发送。"
                        >
                            <Switch />
                        </Form.Item>
                        <Form.Item
                            noStyle
                            shouldUpdate={(prevValues, currentValues) =>
                                prevValues.telegram_notification_quiet_hours_enabled !==
                                currentValues.telegram_notification_quiet_hours_enabled
                            }
                        >
                            {({ getFieldValue }) => {
                                const quietHoursEnabled = Boolean(getFieldValue('telegram_notification_quiet_hours_enabled'));
                                return (
                                    <>
                                        <Form.Item
                                            label="静默开始时间"
                                            name="telegram_notification_quiet_hours_start"
                                            rules={[
                                                {
                                                    validator: async (_, value) => {
                                                        if (!quietHoursEnabled) {
                                                            return;
                                                        }
                                                        const error = validateQuietHourTime(value);
                                                        if (error) {
                                                            throw new Error(error);
                                                        }
                                                    },
                                                },
                                            ]}
                                        >
                                            <Input placeholder="23:00" disabled={!quietHoursEnabled} />
                                        </Form.Item>
                                        <Form.Item
                                            label="静默结束时间"
                                            name="telegram_notification_quiet_hours_end"
                                            rules={[
                                                {
                                                    validator: async (_, value) => {
                                                        if (!quietHoursEnabled) {
                                                            return;
                                                        }
                                                        const error = validateQuietHourTime(value);
                                                        if (error) {
                                                            throw new Error(error);
                                                        }
                                                    },
                                                },
                                            ]}
                                        >
                                            <Input placeholder="08:00" disabled={!quietHoursEnabled} />
                                        </Form.Item>
                                    </>
                                );
                            }}
                        </Form.Item>
                        <Typography.Paragraph className="settings-card__hint">
                            下载完成、下载失败、部分完成和同步结果都会按这里的开关发送到 Telegram。
                            如果未单独填写提醒接收人，会自动回退到允许使用 Bot 的用户 ID 列表。
                            静默时段按服务器本地时间执行，聚合窗口大于 0 时会把窗口内多条通知合并成一条摘要。
                        </Typography.Paragraph>
                    </Card>

                    <Card title="维护与清理" bordered={false} className="console-card settings-card settings-grid__full">
                        <div className="maintenance-stack">
                            <Alert
                                type="warning"
                                showIcon
                                message="这里只清理旧版本遗留项，不会删除当前运行中的 config.yaml、数据库主文件或下载目录。"
                            />

                            <div className="maintenance-block">
                                <div className="maintenance-block__title">旧版 app_config 配置残留</div>
                                <div className="maintenance-block__meta">
                                    当前数量: {legacyState?.legacy_app_config_count || 0}
                                </div>
                                {legacyState?.legacy_app_config_keys?.length ? (
                                    <div className="maintenance-block__detail">
                                        {legacyState.legacy_app_config_keys.join(', ')}
                                    </div>
                                ) : (
                                    <div className="maintenance-block__meta">没有检测到旧版配置键。</div>
                                )}
                                <Popconfirm
                                    title="清理旧版 app_config 键？"
                                    description="会删除数据库里旧版本遗留的配置项，但保留当前 sync_state。"
                                    onConfirm={() => handleCleanupLegacy({ cleanup_app_config: true })}
                                    okText="清理"
                                    cancelText="取消"
                                >
                                    <Button loading={maintenanceLoading} disabled={!legacyState?.legacy_app_config_count}>
                                        清理旧版 app_config
                                    </Button>
                                </Popconfirm>
                            </div>

                            <div className="maintenance-block">
                                <div className="maintenance-block__title">旧版临时 Cookies 文件</div>
                                <div className="maintenance-block__meta">
                                    {legacyState?.temp_cookies_exists
                                        ? `存在：${legacyState.temp_cookies_path}`
                                        : '未检测到 temp_cookies.txt'}
                                </div>
                                <Popconfirm
                                    title="删除 temp_cookies.txt？"
                                    description="仅删除旧版临时 Cookies 文件，不影响当前 config.yaml。"
                                    onConfirm={() => handleCleanupLegacy({ cleanup_temp_cookies: true })}
                                    okText="删除"
                                    cancelText="取消"
                                >
                                    <Button loading={maintenanceLoading} disabled={!legacyState?.temp_cookies_exists}>
                                        删除 temp_cookies.txt
                                    </Button>
                                </Popconfirm>
                            </div>

                            <div className="maintenance-block">
                                <div className="maintenance-block__title">旧版 downloads.zip</div>
                                <div className="maintenance-block__meta">
                                    {legacyState?.downloads_zip_exists
                                        ? `存在：${legacyState.downloads_zip_path}`
                                        : '未检测到 downloads.zip'}
                                </div>
                                <Popconfirm
                                    title="删除 downloads.zip？"
                                    description="仅删除旧版打包产物，不影响当前 downloads 目录。"
                                    onConfirm={() => handleCleanupLegacy({ cleanup_downloads_zip: true })}
                                    okText="删除"
                                    cancelText="取消"
                                >
                                    <Button loading={maintenanceLoading} disabled={!legacyState?.downloads_zip_exists}>
                                        删除 downloads.zip
                                    </Button>
                                </Popconfirm>
                            </div>

                            <div className="console-note">
                                只部署后端时，也可以运行：
                                <code className="ml-1">
                                    python backend/scripts/cleanup_legacy_state.py
                                </code>
                            </div>
                        </div>
                    </Card>
                </div>

                <div className="settings-actions">
                    <Button type="primary" htmlType="submit" loading={saving} size="large">
                        保存所有设置
                    </Button>
                </div>
            </Form>
        </div>
    );
};

export default Settings;
