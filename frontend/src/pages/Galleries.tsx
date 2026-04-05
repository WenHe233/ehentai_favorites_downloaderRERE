import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Button,
    Card,
    Col,
    Dropdown,
    Empty,
    Input,
    Modal,
    Popconfirm,
    Row,
    Select,
    Space,
    Table,
    Tag,
    Tooltip,
    Typography,
    message,
} from 'antd';
import {
    DeleteOutlined,
    DownOutlined,
    FileTextOutlined,
    FolderOpenOutlined,
    ReloadOutlined,
    SearchOutlined,
    SyncOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps, TablePaginationConfig } from 'antd';
import api from '../lib/api';
import type { GalleryProgress, GalleryProgressEvent } from '../lib/download-events';
import { useDownloadEventStream } from '../lib/download-events';
import GalleryProgressPanel from '../components/GalleryProgressPanel';
import ResizableHeaderCell from '../components/ResizableHeaderCell';
import StatusPill from '../components/StatusPill';

interface LogEntry {
    time: string;
    level: string;
    msg: string;
}

interface Gallery {
    gid: number;
    token: string;
    title: string;
    status: string;
    filecount: number;
    posted?: string | null;
    downloaded_at?: string | null;
    favorited_at?: string | null;
    error_msg?: string | null;
    parent_gid?: string | null;
    requested_quality?: string | null;
    resolved_quality?: string | null;
    progress?: GalleryProgress | null;
}

interface GalleryListResponse {
    items: Gallery[];
    total: number;
    skip: number;
    limit: number;
}

interface GalleryLogsResponse {
    gid: number;
    token: string;
    title: string;
    error_msg?: string | null;
    requested_quality?: string | null;
    resolved_quality?: string | null;
    logs: LogEntry[];
}

const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_COLUMN_WIDTHS = {
    gallery: 460,
    gid: 120,
    favorited_at: 190,
    status: 150,
    progress: 320,
    filecount: 90,
    downloaded_at: 190,
    action: 220,
} as const;

const COLUMN_MIN_WIDTHS: Record<string, number> = {
    gallery: 320,
    gid: 100,
    favorited_at: 170,
    status: 120,
    progress: 260,
    filecount: 80,
    downloaded_at: 170,
    action: 200,
};

const statusOptions = [
    { value: '', label: '全部状态' },
    { value: 'pending', label: '等待中' },
    { value: 'downloading', label: '下载中' },
    { value: 'completed', label: '已完成' },
    { value: 'partial', label: '部分完成' },
    { value: 'failed', label: '失败' },
    { value: 'outdated', label: '待更新' },
];

const formatUtcToLocal = (utcString: string | null | undefined): string => {
    if (!utcString) {
        return '-';
    }

    try {
        const normalized = utcString.includes('T') ? utcString : utcString.replace(' ', 'T');
        const withTimezone = /(?:Z|[+-]\d{2}:\d{2})$/.test(normalized) ? normalized : `${normalized}Z`;
        const date = new Date(withTimezone);
        return Number.isNaN(date.getTime()) ? utcString : date.toLocaleString();
    } catch {
        return '-';
    }
};

const formatQualityLabel = (value: string | null | undefined): string | null => {
    if (value === 'original') {
        return '原图';
    }
    if (value === 'native') {
        return '展示图';
    }
    return null;
};

const buildQualitySummary = (
    requestedQuality: string | null | undefined,
    resolvedQuality: string | null | undefined
): string | null => {
    const resolvedLabel = formatQualityLabel(resolvedQuality);
    if (resolvedLabel) {
        if (requestedQuality === 'original' && resolvedQuality === 'native') {
            return `最终质量：${resolvedLabel}（自动降级）`;
        }
        return `最终质量：${resolvedLabel}`;
    }

    const requestedLabel = formatQualityLabel(requestedQuality);
    if (requestedLabel) {
        return `请求质量：${requestedLabel}`;
    }

    return null;
};

const hasOwn = <T extends object>(value: T, key: string) =>
    Object.prototype.hasOwnProperty.call(value, key);

const Galleries: React.FC = () => {
    const [data, setData] = useState<Gallery[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
    const [searchText, setSearchText] = useState('');
    const [statusFilter, setStatusFilter] = useState('');
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [total, setTotal] = useState(0);
    const [columnWidths, setColumnWidths] = useState<Record<string, number>>(() => ({ ...DEFAULT_COLUMN_WIDTHS }));

    const [logModalVisible, setLogModalVisible] = useState(false);
    const [currentLogGallery, setCurrentLogGallery] = useState<Gallery | null>(null);
    const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
    const [logLoading, setLogLoading] = useState(false);
    const [logError, setLogError] = useState<string | null>(null);

    const fetchGalleries = useCallback(
        async (page = currentPage, size = pageSize) => {
            setLoading(true);

            try {
                const response = await api.get<GalleryListResponse>('/galleries', {
                    params: {
                        skip: (page - 1) * size,
                        limit: size,
                        status: statusFilter || undefined,
                        search: searchText.trim() || undefined,
                    },
                });

                const maxPage = Math.max(1, Math.ceil(response.data.total / size));
                if (response.data.total > 0 && page > maxPage) {
                    setCurrentPage(maxPage);
                    return;
                }

                setData(response.data.items);
                setTotal(response.data.total);
            } catch (error) {
                console.error(error);
                message.error('加载画廊列表失败');
            } finally {
                setLoading(false);
            }
        },
        [currentPage, pageSize, searchText, statusFilter]
    );

    const updateGalleryFromEvent = useCallback((payload: GalleryProgressEvent) => {
        setData((current) =>
            current.map((item) =>
                item.gid === payload.gid
                    ? (() => {
                          const nextStatus = payload.status || item.status;
                          const hasErrorMsg = hasOwn(payload, 'error_msg');
                          const hasDownloadedAt = hasOwn(payload, 'downloaded_at');
                          const hasRequestedQuality = hasOwn(payload, 'requested_quality');
                          const hasResolvedQuality = hasOwn(payload, 'resolved_quality');

                          let nextErrorMsg = hasErrorMsg ? (payload.error_msg ?? null) : item.error_msg;
                          let nextDownloadedAt = hasDownloadedAt ? (payload.downloaded_at ?? null) : item.downloaded_at;
                          let nextRequestedQuality = hasRequestedQuality
                              ? (payload.requested_quality ?? null)
                              : item.requested_quality;
                          let nextResolvedQuality = hasResolvedQuality
                              ? (payload.resolved_quality ?? null)
                              : item.resolved_quality;

                          if (!hasErrorMsg && ['pending', 'downloading', 'completed', 'cancelled'].includes(nextStatus)) {
                              nextErrorMsg = null;
                          }

                          if (!hasDownloadedAt && ['pending', 'downloading', 'failed', 'partial', 'cancelled'].includes(nextStatus)) {
                              nextDownloadedAt = null;
                          }

                          if (!hasResolvedQuality && ['pending', 'downloading', 'cancelled'].includes(nextStatus)) {
                              nextResolvedQuality = null;
                          }

                          if (!hasRequestedQuality && ['pending', 'cancelled'].includes(nextStatus)) {
                              nextRequestedQuality = null;
                          }

                          return {
                              ...item,
                              title: payload.title || item.title,
                              status: nextStatus,
                              error_msg: nextErrorMsg,
                              downloaded_at: nextDownloadedAt,
                              requested_quality: nextRequestedQuality,
                              resolved_quality: nextResolvedQuality,
                              progress: payload.progress || item.progress,
                          };
                      })()
                    : item
            )
        );
    }, []);

    const { connectionState } = useDownloadEventStream({
        onSnapshot: (payload) => {
            setData((current) =>
                current.map((item) => {
                    const live = payload.active_galleries.find((entry) => entry.gid === item.gid);
                    if (!live) {
                        return item;
                    }

                    return {
                        ...item,
                        title: live.title || item.title,
                        status: live.status || item.status,
                        error_msg:
                            (live.status || item.status) === 'downloading'
                                ? null
                                : hasOwn(live, 'error_msg')
                                  ? (live.error_msg ?? null)
                                  : item.error_msg,
                        downloaded_at:
                            (live.status || item.status) === 'downloading'
                                ? null
                                : live.downloaded_at ?? item.downloaded_at,
                        requested_quality: live.requested_quality ?? item.requested_quality ?? null,
                        resolved_quality:
                            (live.status || item.status) === 'downloading'
                                ? null
                                : live.resolved_quality ?? item.resolved_quality ?? null,
                        progress: live.progress || item.progress,
                    };
                })
            );
        },
        onGalleryProgress: updateGalleryFromEvent,
        onGalleryStatus: updateGalleryFromEvent,
        onReconnected: () => {
            void fetchGalleries();
        },
    });

    useEffect(() => {
        const timeout = window.setTimeout(() => {
            void fetchGalleries();
        }, searchText ? 250 : 0);

        return () => {
            window.clearTimeout(timeout);
        };
    }, [fetchGalleries, searchText]);

    const refreshCurrentPage = useCallback(async () => {
        await fetchGalleries();
    }, [fetchGalleries]);

    const handleDeleteRecord = useCallback(async (gid: number) => {
        try {
            await api.delete(`/galleries/${gid}`);
            message.success('记录已删除');
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('删除失败');
        }
    }, [refreshCurrentPage]);

    const handleDeleteWithFiles = useCallback(async (gid: number) => {
        try {
            const response = await api.delete(`/galleries/${gid}/with-files`);
            const { was_downloading, files_deleted } = response.data as {
                was_downloading?: boolean;
                files_deleted?: number;
            };
            let text = '记录和文件已删除';
            if (was_downloading) {
                text += '（已终止下载）';
            }
            if (files_deleted) {
                text += `，删除了 ${files_deleted} 个文件`;
            }
            message.success(text);
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('删除失败');
        }
    }, [refreshCurrentPage]);

    const handleReset = useCallback(async (gid: number) => {
        try {
            await api.post(`/galleries/${gid}/reset`);
            message.success('已重置为等待下载');
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('重置失败');
        }
    }, [refreshCurrentPage]);

    const handleDeleteAll = async () => {
        try {
            await api.delete('/galleries');
            message.success('所有画廊已删除');
            setSelectedRowKeys([]);
            setCurrentPage(1);
            await fetchGalleries(1, pageSize);
        } catch (error) {
            console.error(error);
            message.error('删除失败');
        }
    };

    const handleViewLog = useCallback(async (gallery: Gallery) => {
        setCurrentLogGallery(gallery);
        setLogLoading(true);
        setLogError(null);
        setLogEntries([]);
        setLogModalVisible(true);

        try {
            const response = await api.get<GalleryLogsResponse>(`/galleries/${gallery.gid}/logs`);
            setLogEntries(response.data.logs || []);
            setLogError(response.data.error_msg || null);
            setCurrentLogGallery((current) =>
                current
                    ? {
                          ...current,
                          requested_quality: response.data.requested_quality ?? current.requested_quality ?? null,
                          resolved_quality: response.data.resolved_quality ?? current.resolved_quality ?? null,
                      }
                    : current
            );
        } catch (error) {
            console.error(error);
            setLogError('加载日志失败');
        } finally {
            setLogLoading(false);
        }
    }, []);

    const handleBatchReset = async () => {
        try {
            let successCount = 0;
            for (const gid of selectedRowKeys) {
                try {
                    await api.post(`/galleries/${gid}/reset`);
                    successCount += 1;
                } catch (error) {
                    console.error(`Failed to reset ${gid}`, error);
                }
            }
            message.success(`已重置 ${successCount} 个画廊`);
            setSelectedRowKeys([]);
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('批量重置失败');
        }
    };

    const handleBatchDeleteRecord = async () => {
        try {
            let successCount = 0;
            for (const gid of selectedRowKeys) {
                try {
                    await api.delete(`/galleries/${gid}`);
                    successCount += 1;
                } catch (error) {
                    console.error(`Failed to delete ${gid}`, error);
                }
            }
            message.success(`已删除 ${successCount} 条记录`);
            setSelectedRowKeys([]);
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('批量删除失败');
        }
    };

    const handleBatchDeleteWithFiles = async () => {
        try {
            let successCount = 0;
            let filesDeleted = 0;
            for (const gid of selectedRowKeys) {
                try {
                    const response = await api.delete(`/galleries/${gid}/with-files`);
                    successCount += 1;
                    filesDeleted += (response.data as { files_deleted?: number }).files_deleted || 0;
                } catch (error) {
                    console.error(`Failed to delete ${gid}`, error);
                }
            }
            message.success(`已删除 ${successCount} 条记录，${filesDeleted} 个文件`);
            setSelectedRowKeys([]);
            await refreshCurrentPage();
        } catch (error) {
            console.error(error);
            message.error('批量删除失败');
        }
    };

    const getDeleteMenuItems = useCallback((gid: number): MenuProps['items'] => [
        {
            key: 'record',
            label: '仅删除记录',
            icon: <DeleteOutlined />,
            onClick: () => {
                void handleDeleteRecord(gid);
            },
        },
        {
            key: 'with-files',
            label: '删除记录和文件',
            icon: <FolderOpenOutlined />,
            danger: true,
            onClick: () => {
                void handleDeleteWithFiles(gid);
            },
        },
    ], [handleDeleteRecord, handleDeleteWithFiles]);

    const resizeColumn = useCallback((key: string, nextWidth: number) => {
        setColumnWidths((current) => ({
            ...current,
            [key]: nextWidth,
        }));
    }, []);

    const columns: ColumnsType<Gallery> = useMemo(() => {
        const baseColumns: ColumnsType<Gallery> = [
            {
                title: '画廊',
                key: 'gallery',
                width: columnWidths.gallery,
                render: (_value: unknown, record: Gallery) => (
                    <div className="gallery-title-cell">
                        <Tooltip title={record.title} placement="topLeft">
                            <div className="gallery-title-clamp">{record.title}</div>
                        </Tooltip>
                        {record.parent_gid && (
                            <button
                                className="gallery-link-button"
                                onClick={(event) => {
                                    event.stopPropagation();
                                    setSearchText(record.parent_gid || '');
                                    setCurrentPage(1);
                                }}
                                type="button"
                            >
                                来自旧版本 {record.parent_gid}
                            </button>
                        )}
                    </div>
                ),
            },
            {
                title: 'GID',
                dataIndex: 'gid',
                key: 'gid',
                width: columnWidths.gid,
                render: (value: number) => <span className="gallery-mono">{value}</span>,
            },
            {
                title: '收藏时间',
                dataIndex: 'favorited_at',
                key: 'favorited_at',
                width: columnWidths.favorited_at,
                render: (text: Gallery['favorited_at']) => formatUtcToLocal(text),
            },
            {
                title: '状态',
                key: 'status',
                width: columnWidths.status,
                render: (_value: unknown, record: Gallery) => (
                    <div className="space-y-2">
                        <StatusPill status={record.status || 'pending'} />
                        {buildQualitySummary(record.requested_quality, record.resolved_quality) && (
                            <div className="text-[11px] text-[var(--app-text-muted)]">
                                {buildQualitySummary(record.requested_quality, record.resolved_quality)}
                            </div>
                        )}
                        {record.error_msg && (
                            <Tooltip title={record.error_msg}>
                                <div className="gallery-error-clamp">{record.error_msg}</div>
                            </Tooltip>
                        )}
                    </div>
                ),
            },
            {
                title: '进度',
                dataIndex: 'progress',
                key: 'progress',
                width: columnWidths.progress,
                render: (progress: Gallery['progress']) => <GalleryProgressPanel progress={progress} compact />,
            },
            {
                title: '文件数',
                dataIndex: 'filecount',
                key: 'filecount',
                width: columnWidths.filecount,
                render: (value: number) => <span>{value || '-'}</span>,
            },
            {
                title: '完成时间',
                dataIndex: 'downloaded_at',
                key: 'downloaded_at',
                width: columnWidths.downloaded_at,
                render: (text: Gallery['downloaded_at']) => formatUtcToLocal(text),
            },
            {
                title: '操作',
                key: 'action',
                width: columnWidths.action,
                render: (_value: unknown, record: Gallery) => (
                    <Space size="small">
                        <Button
                            type="link"
                            size="small"
                            icon={<FileTextOutlined />}
                            onClick={() => {
                                void handleViewLog(record);
                            }}
                        >
                            日志
                        </Button>
                        <Button
                            type="link"
                            size="small"
                            icon={<ReloadOutlined />}
                            onClick={() => {
                                void handleReset(record.gid);
                            }}
                        >
                            重试
                        </Button>
                        <Dropdown menu={{ items: getDeleteMenuItems(record.gid) }} trigger={['click']}>
                            <Button type="link" size="small" danger>
                                删除 <DownOutlined />
                            </Button>
                        </Dropdown>
                    </Space>
                ),
            },
        ];

        return baseColumns.map((column) => {
            const dataIndex = 'dataIndex' in column ? column.dataIndex : undefined;
            const columnKey = String(column.key ?? dataIndex ?? '');
            return {
                ...column,
                onHeaderCell: () => ({
                    width: typeof column.width === 'number' ? column.width : undefined,
                    minWidth: COLUMN_MIN_WIDTHS[columnKey] ?? 90,
                    onResize: (nextWidth: number) => resizeColumn(columnKey, nextWidth),
                }),
            };
        });
    }, [columnWidths, getDeleteMenuItems, handleReset, handleViewLog, resizeColumn, setSearchText]);

    const totalColumnWidth = useMemo(
        () => Object.values(columnWidths).reduce((sum, width) => sum + width, 64),
        [columnWidths]
    );

    const rowSelection = {
        preserveSelectedRowKeys: true,
        selectedRowKeys,
        onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
    };

    const hasSelected = selectedRowKeys.length > 0;

    const getLogLevelColor = (level: string) => {
        if (level === 'error') return '#fb7185';
        if (level === 'success') return '#22c55e';
        if (level === 'warning') return '#f59e0b';
        return '#38bdf8';
    };

    const handleTableChange = (pagination: TablePaginationConfig) => {
        setCurrentPage(pagination.current || 1);
        setPageSize(pagination.pageSize || DEFAULT_PAGE_SIZE);
    };

    const connectionTagColor = useMemo(() => {
        if (connectionState === 'connected') return 'success';
        if (connectionState === 'reconnecting') return 'processing';
        if (connectionState === 'connecting') return 'processing';
        return 'warning';
    }, [connectionState]);

    return (
        <div className="space-y-6">
            <section className="console-hero">
                <div>
                    <div className="console-kicker">Task Center</div>
                    <h1 className="console-title">任务中心</h1>
                    <p className="console-description">
                        在这里筛选任务、查看下载结果、重试失败项目，并按需删除记录或文件。
                    </p>
                </div>
                <div className="console-actions">
                    <Tag color={connectionTagColor}>{connectionState === 'connected' ? '实时链路正常' : connectionState === 'reconnecting' ? '实时链路重连中' : '实时链路建立中'}</Tag>
                    <Button
                        icon={<SyncOutlined />}
                        onClick={() => {
                            void refreshCurrentPage();
                        }}
                        loading={loading}
                    >
                        刷新当前页
                    </Button>
                    <Popconfirm
                        title="确定删除所有画廊记录？"
                        description="此操作不可恢复"
                        onConfirm={handleDeleteAll}
                        okText="确定"
                        cancelText="取消"
                    >
                        <Button danger>清空所有</Button>
                    </Popconfirm>
                </div>
            </section>

            <Card className="console-card" bordered={false}>
                <Row gutter={[16, 16]}>
                    <Col xs={24} lg={8}>
                        <Input
                            placeholder="搜索 GID、标题或旧版本 GID..."
                            prefix={<SearchOutlined />}
                            value={searchText}
                            onChange={(event) => {
                                setSearchText(event.target.value);
                                setCurrentPage(1);
                            }}
                            allowClear
                        />
                    </Col>
                    <Col xs={24} sm={12} lg={4}>
                        <Select
                            style={{ width: '100%' }}
                            value={statusFilter}
                            onChange={(value) => {
                                setStatusFilter(value);
                                setCurrentPage(1);
                            }}
                            options={statusOptions}
                        />
                    </Col>
                    <Col xs={24} sm={12} lg={12}>
                        {hasSelected ? (
                            <Space wrap>
                                <span className="text-sm text-[var(--app-text-muted)]">
                                    已选择 {selectedRowKeys.length} 项
                                </span>
                                <Button
                                    onClick={() => {
                                        void handleBatchReset();
                                    }}
                                    icon={<ReloadOutlined />}
                                >
                                    批量重试
                                </Button>
                                <Popconfirm
                                    title={`确定删除 ${selectedRowKeys.length} 条记录？`}
                                    onConfirm={handleBatchDeleteRecord}
                                    okText="确定"
                                    cancelText="取消"
                                >
                                    <Button icon={<DeleteOutlined />}>批量删除记录</Button>
                                </Popconfirm>
                                <Popconfirm
                                    title={`确定删除 ${selectedRowKeys.length} 条记录及其文件？`}
                                    description="此操作将终止下载并删除已下载文件"
                                    onConfirm={handleBatchDeleteWithFiles}
                                    okText="确定"
                                    cancelText="取消"
                                >
                                    <Button danger icon={<FolderOpenOutlined />}>
                                        批量删除(含文件)
                                    </Button>
                                </Popconfirm>
                            </Space>
                        ) : (
                            <div className="text-sm text-[var(--app-text-muted)]">
                                当前列表共 {total} 条记录
                            </div>
                        )}
                    </Col>
                </Row>
            </Card>

            <Card className="console-card console-card--elevated" bordered={false}>
                {data.length === 0 && !loading ? (
                    <Empty description="当前筛选条件下没有画廊记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                    <Table
                        components={{ header: { cell: ResizableHeaderCell } }}
                        rowSelection={rowSelection}
                        columns={columns}
                        dataSource={data}
                        rowKey="gid"
                        loading={loading}
                        size="middle"
                        tableLayout="fixed"
                        scroll={{ x: totalColumnWidth }}
                        pagination={{
                            current: currentPage,
                            pageSize,
                            total,
                            showSizeChanger: true,
                            pageSizeOptions: ['10', '20', '50', '100'],
                            showTotal: (count, range) => `第 ${range[0]}-${range[1]} 条，共 ${count} 条`,
                        }}
                        onChange={handleTableChange}
                    />
                )}
            </Card>

            <Modal
                title={`下载日志 - ${currentLogGallery?.title?.substring(0, 50) || ''}`}
                open={logModalVisible}
                onCancel={() => setLogModalVisible(false)}
                footer={null}
                width={760}
            >
                {logError && (
                    <div className="mb-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 p-4 text-sm text-rose-500">
                        {logError}
                    </div>
                )}

                {buildQualitySummary(currentLogGallery?.requested_quality, currentLogGallery?.resolved_quality) && (
                    <div className="mb-4 rounded-2xl border border-[var(--app-border-strong)] bg-[var(--app-soft)] p-4 text-sm text-[var(--app-text-secondary)]">
                        {buildQualitySummary(currentLogGallery?.requested_quality, currentLogGallery?.resolved_quality)}
                    </div>
                )}

                {logLoading ? (
                    <div className="py-10 text-center text-[var(--app-text-muted)]">日志加载中...</div>
                ) : logEntries.length === 0 ? (
                    <div className="py-10 text-center text-[var(--app-text-muted)]">暂无日志</div>
                ) : (
                    <div className="space-y-3">
                        {logEntries.map((entry, index) => (
                            <div key={`${entry.time}-${index}`} className="task-log-entry">
                                <div className="task-log-entry__time">
                                    {new Date(entry.time).toLocaleTimeString()}
                                </div>
                                <div className="task-log-entry__body">
                                    <Typography.Text style={{ color: getLogLevelColor(entry.level) }}>
                                        [{entry.level.toUpperCase()}]
                                    </Typography.Text>
                                    <Typography.Text className="!ml-2 !text-[var(--app-text-primary)]">
                                        {entry.msg}
                                    </Typography.Text>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </Modal>
        </div>
    );
};

export default Galleries;
