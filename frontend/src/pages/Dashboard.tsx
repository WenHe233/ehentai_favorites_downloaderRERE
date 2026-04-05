import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
    Alert,
    Button,
    Card,
    Col,
    Empty,
    Input,
    Row,
    Statistic,
    message,
} from 'antd';
import {
    CheckCircleOutlined,
    CloudDownloadOutlined,
    DollarCircleOutlined,
    LinkOutlined,
    RadarChartOutlined,
    SyncOutlined,
    WarningOutlined,
} from '@ant-design/icons';
import api from '../lib/api';
import {
    type DownloadSnapshotEvent,
    type GalleryProgressEvent,
    type SyncStatusEvent,
    useDownloadEventStream,
} from '../lib/download-events';
import GalleryProgressPanel from '../components/GalleryProgressPanel';
import StatusPill from '../components/StatusPill';

interface StatusResponse {
    downloader_running: boolean;
    queue_len: number;
    active_downloads: number;
    max_concurrent_downloads: number;
    failed_retry_count: number;
    last_sync_ts?: string | null;
    sync_running: boolean;
    sync_last_error?: string | null;
}

interface AccountResponse {
    gp: number | null;
    credits: number | null;
}

interface SyncActionResponse {
    status: 'started' | 'already_running';
    message: string;
}

interface ManualDownloadResponse {
    status: 'Added' | 'Queued' | 'Exists';
    msg: string;
}

const formatNumber = (value: number | null | undefined) => {
    if (value === null || value === undefined) {
        return 'N/A';
    }
    return value.toLocaleString();
};

const formatSyncTimestamp = (value: string | null | undefined) => {
    if (!value) {
        return '未同步';
    }

    try {
        const date = new Date(value.replace(' ', 'T') + 'Z');
        return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
    } catch {
        return value;
    }
};

const sortActiveGalleries = (items: GalleryProgressEvent[]) =>
    [...items].sort((left, right) => right.gid - left.gid);

const Dashboard: React.FC = () => {
    const [status, setStatus] = useState<StatusResponse | null>(null);
    const [account, setAccount] = useState<AccountResponse | null>(null);
    const [syncRequesting, setSyncRequesting] = useState(false);
    const [urlInput, setUrlInput] = useState('');
    const [downloading, setDownloading] = useState(false);
    const [activeGalleries, setActiveGalleries] = useState<GalleryProgressEvent[]>([]);

    const fetchStatus = useCallback(async () => {
        try {
            const response = await api.get<StatusResponse>('/status');
            setStatus(response.data);
        } catch (error) {
            console.error(error);
        }
    }, []);

    const fetchAccount = useCallback(async () => {
        try {
            const response = await api.get<AccountResponse>('/account');
            setAccount(response.data);
        } catch (error) {
            console.error(error);
        }
    }, []);

    const applySyncStatus = useCallback((payload: SyncStatusEvent) => {
        setStatus((current) =>
            current
                ? {
                      ...current,
                      sync_running: payload.sync_running,
                      sync_last_error: payload.sync_last_error || null,
                      last_sync_ts: payload.last_sync_ts || null,
                  }
                : {
                      downloader_running: false,
                      queue_len: 0,
                      active_downloads: 0,
                      max_concurrent_downloads: 0,
                      failed_retry_count: 0,
                      last_sync_ts: payload.last_sync_ts || null,
                      sync_running: payload.sync_running,
                      sync_last_error: payload.sync_last_error || null,
                  }
        );
    }, []);

    const upsertActiveGallery = useCallback((payload: GalleryProgressEvent) => {
        setActiveGalleries((current) => {
            const next = [...current];
            const index = next.findIndex((item) => item.gid === payload.gid);
            if (index >= 0) {
                next[index] = { ...next[index], ...payload };
            } else {
                next.push(payload);
            }
            return sortActiveGalleries(next);
        });
    }, []);

    const removeActiveGallery = useCallback((gid: number) => {
        setActiveGalleries((current) => current.filter((item) => item.gid !== gid));
    }, []);

    const { connectionState, isConnected } = useDownloadEventStream({
        onSnapshot: (payload: DownloadSnapshotEvent) => {
            setActiveGalleries(sortActiveGalleries(payload.active_galleries));
            applySyncStatus(payload.sync_status);
            setStatus((current) =>
                current
                    ? {
                          ...current,
                          active_downloads: payload.active_galleries.length,
                          downloader_running: payload.downloader_running,
                      }
                    : current
            );
        },
        onGalleryProgress: (payload) => {
            upsertActiveGallery(payload);
            setStatus((current) =>
                current
                    ? {
                          ...current,
                          active_downloads: Math.max(current.active_downloads, 1),
                      }
                    : current
            );
        },
        onGalleryStatus: (payload) => {
            if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
                removeActiveGallery(payload.gid);
            } else {
                upsertActiveGallery(payload);
            }
        },
        onSyncStatus: applySyncStatus,
        onReconnected: () => {
            void fetchStatus();
        },
    });

    const triggerSync = async () => {
        try {
            setSyncRequesting(true);
            const response = await api.post<SyncActionResponse>('/action/sync');
            if (response.data.status === 'already_running') {
                message.info('同步任务已经在后台运行');
            } else {
                message.success('同步任务已在后台启动');
            }
            await fetchStatus();
        } catch (error) {
            console.error(error);
            message.error('触发失败');
        } finally {
            setSyncRequesting(false);
        }
    };

    const handleUrlDownload = async () => {
        if (!urlInput.trim()) {
            message.warning('请输入画廊链接');
            return;
        }

        const urls = urlInput
            .split(/[\n,，\s]+/)
            .map((item) => item.trim())
            .filter((item) => item.length > 0 && item.includes('/g/'));

        if (urls.length === 0) {
            message.warning('请输入有效的画廊链接 (需包含 /g/)');
            return;
        }

        try {
            setDownloading(true);
            let successCount = 0;
            let failCount = 0;
            let timeoutCount = 0;

            for (const url of urls) {
                try {
                    await api.post<ManualDownloadResponse>(
                        '/download/manual',
                        { url },
                        {
                            // 手动补链会先检查新版并受站点限速影响，10s 很容易误判成前端失败
                            timeout: 45000,
                        }
                    );
                    successCount += 1;
                } catch (error) {
                    if (axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
                        timeoutCount += 1;
                    } else {
                        failCount += 1;
                    }
                }
            }

            if (failCount === 0 && timeoutCount === 0) {
                message.success(`已添加 ${successCount} 个画廊到下载队列`);
            } else if (failCount === 0) {
                message.info(
                    `已确认 ${successCount} 个，另有 ${timeoutCount} 个请求等待超时。后台可能仍在校验或入队，请到任务中心确认。`
                );
            } else if (timeoutCount === 0) {
                message.warning(`成功 ${successCount} 个，失败 ${failCount} 个`);
            } else {
                message.warning(
                    `已确认 ${successCount} 个，失败 ${failCount} 个，另有 ${timeoutCount} 个请求等待超时。后台可能仍在继续处理。`
                );
            }

            setUrlInput('');
            await fetchStatus();
        } catch (error) {
            console.error(error);
            message.error('批量添加失败');
        } finally {
            setDownloading(false);
        }
    };

    useEffect(() => {
        void fetchStatus();
        void fetchAccount();
    }, [fetchAccount, fetchStatus]);

    useEffect(() => {
        const intervalMs = isConnected ? 25000 : 12000;
        const timer = window.setInterval(() => {
            void fetchStatus();
        }, intervalMs);

        return () => {
            window.clearInterval(timer);
        };
    }, [fetchStatus, isConnected]);

    const syncInProgress = Boolean(status?.sync_running);

    const connectionLabel = useMemo(() => {
        if (connectionState === 'connected') {
            return 'SSE 已连接';
        }
        if (connectionState === 'reconnecting') {
            return 'SSE 重连中';
        }
        if (connectionState === 'connecting') {
            return 'SSE 连接中';
        }
        return 'SSE 已断开';
    }, [connectionState]);

    return (
        <div className="dashboard-page space-y-6">
            <section className="console-hero">
                <div>
                    <div className="console-kicker">Dashboard</div>
                    <h1 className="console-title">仪表盘</h1>
                    <p className="console-description">
                        在这里集中查看下载运行情况、同步结果和账户余额，也可以快速补充新的下载任务。
                    </p>
                </div>
                <div className="console-actions">
                    <span className={`console-connection console-connection--${connectionState}`}>
                        {connectionLabel}
                    </span>
                    <Button
                        type="primary"
                        size="large"
                        icon={<SyncOutlined spin={syncRequesting || syncInProgress} />}
                        onClick={triggerSync}
                        loading={syncRequesting}
                        disabled={syncInProgress}
                    >
                        {syncInProgress ? '同步进行中' : '立即同步'}
                    </Button>
                </div>
            </section>

            <Row gutter={[16, 16]} className="dashboard-summary-row">
                <Col xs={24} sm={12} xl={6} className="dashboard-summary-row__col">
                    <Card className="console-card dashboard-summary-card" bordered={false}>
                        <Statistic
                            title="下载服务"
                            value={status?.downloader_running ? '在线' : '离线'}
                            prefix={<CheckCircleOutlined />}
                            valueStyle={{ color: status?.downloader_running ? 'var(--app-success)' : 'var(--app-danger)' }}
                        />
                    </Card>
                </Col>
                <Col xs={24} sm={12} xl={6} className="dashboard-summary-row__col">
                    <Card className="console-card dashboard-summary-card" bordered={false}>
                        <Statistic title="等待队列" value={status?.queue_len || 0} prefix={<CloudDownloadOutlined />} />
                    </Card>
                </Col>
                <Col xs={24} sm={12} xl={6} className="dashboard-summary-row__col">
                    <Card className="console-card dashboard-summary-card" bordered={false}>
                        <Statistic
                            title="失败重试"
                            value={status?.failed_retry_count || 0}
                            prefix={<WarningOutlined />}
                            valueStyle={{ color: (status?.failed_retry_count || 0) > 0 ? 'var(--app-warning)' : undefined }}
                        />
                    </Card>
                </Col>
                <Col xs={24} sm={12} xl={6} className="dashboard-summary-row__col">
                    <Card className="console-card dashboard-summary-card dashboard-sync-card" bordered={false}>
                        <div className="dashboard-sync-card__label">同步状态</div>
                        <div className="dashboard-sync-card__value">
                            <RadarChartOutlined className="dashboard-sync-card__icon" />
                            <span
                                style={{
                                    color: syncInProgress ? 'var(--app-accent-strong)' : 'var(--app-text-muted)',
                                }}
                            >
                                {syncInProgress ? '运行中' : '空闲'}
                            </span>
                        </div>
                        <div className="dashboard-sync-card__meta">
                            上次同步完成：{formatSyncTimestamp(status?.last_sync_ts)}
                        </div>
                    </Card>
                </Col>
            </Row>

            <Row gutter={[16, 16]} className="dashboard-detail-row">
                <Col xs={24} xl={16} className="dashboard-detail-row__col">
                    <Card
                        className="console-card console-card--elevated dashboard-detail-card dashboard-detail-card--tasks"
                        bordered={false}
                        title="活跃下载任务"
                        extra={
                            <span className="text-[var(--app-text-muted)]">
                                {activeGalleries.length} / {status?.max_concurrent_downloads || 0}
                            </span>
                        }
                    >
                        {activeGalleries.length === 0 ? (
                            <div className="dashboard-detail-empty">
                                <Empty description="当前没有活跃下载任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                            </div>
                        ) : (
                            <div className="grid gap-4 md:grid-cols-2">
                                {activeGalleries.map((gallery) => (
                                    <div key={gallery.gid} className="task-card">
                                        <div className="task-card__header">
                                            <div>
                                                <div className="task-card__title">{gallery.title || `Gallery ${gallery.gid}`}</div>
                                                <div className="task-card__meta">GID {gallery.gid}</div>
                                            </div>
                                            <StatusPill status={gallery.status || 'downloading'} />
                                        </div>
                                        <GalleryProgressPanel progress={gallery.progress} />
                                    </div>
                                ))}
                            </div>
                        )}
                    </Card>
                </Col>

                <Col xs={24} xl={8} className="dashboard-detail-row__col">
                    <Card className="console-card dashboard-detail-card" bordered={false} title="余额与同步信息">
                        <div className="space-y-4">
                            <div className="console-metric-row">
                                <div>
                                    <div className="console-metric-label">账户 GP</div>
                                    <div className="console-metric-value">{formatNumber(account?.gp)}</div>
                                </div>
                                <DollarCircleOutlined className="console-metric-icon" />
                            </div>
                            <div className="console-metric-row">
                                <div>
                                    <div className="console-metric-label">账户 Credits</div>
                                    <div className="console-metric-value">{formatNumber(account?.credits)}</div>
                                </div>
                                <DollarCircleOutlined className="console-metric-icon" />
                            </div>
                            {status?.sync_last_error ? (
                                <Alert
                                    type="error"
                                    showIcon
                                    message="最近一次同步报错"
                                    description={status.sync_last_error}
                                />
                            ) : (
                                <Alert
                                    type="success"
                                    showIcon
                                    message="同步链路正常"
                                    description="最近没有检测到同步错误。"
                                />
                            )}
                        </div>
                    </Card>
                </Col>
            </Row>

            <Card className="console-card console-card--elevated" title="任务投递面板" bordered={false}>
                <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
                    <Input.TextArea
                        placeholder={`输入画廊链接，每行一个，或用逗号分隔\n例如:\nhttps://exhentai.org/g/3708716/efebefd158/\nhttps://exhentai.org/g/3709085/e5c2a34ba1/`}
                        rows={5}
                        value={urlInput}
                        onChange={(event) => setUrlInput(event.target.value)}
                    />
                    <div className="flex items-end">
                        <Button
                            type="primary"
                            icon={<LinkOutlined />}
                            loading={downloading}
                            onClick={handleUrlDownload}
                            size="large"
                            className="w-full lg:w-auto"
                        >
                            批量加入队列
                        </Button>
                    </div>
                </div>
            </Card>
        </div>
    );
};

export default Dashboard;
