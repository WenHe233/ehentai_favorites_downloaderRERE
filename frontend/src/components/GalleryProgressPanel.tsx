import React from 'react';
import { Progress, Typography } from 'antd';
import type { GalleryProgress } from '../lib/download-events';

interface GalleryProgressPanelProps {
    progress?: GalleryProgress | null;
    compact?: boolean;
}

const phaseTextMap: Record<string, string> = {
    queued: '等待队列',
    preparing: '准备中',
    polling: '轮询中',
    downloading: '下载中',
    packaging: '打包中',
    verifying: '校验中',
    completed: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
};

const formatAmount = (value: number | null, unit: GalleryProgress['unit']) => {
    if (value === null) {
        return null;
    }

    if (unit === 'bytes') {
        return `${(value / (1024 * 1024)).toFixed(2)} MiB`;
    }

    return `${value}`;
};

const GalleryProgressPanel: React.FC<GalleryProgressPanelProps> = ({ progress, compact = false }) => {
    if (!progress) {
        return (
            <div className="text-xs text-[var(--app-text-muted)]">
                暂无进度
            </div>
        );
    }

    const status =
        progress.phase === 'failed'
            ? 'exception'
            : progress.phase === 'completed'
              ? 'success'
              : progress.phase === 'partial'
                ? 'normal'
              : 'active';
    const strokeColor =
        progress.phase === 'partial'
            ? 'var(--app-warning)'
            : progress.phase === 'failed'
              ? 'var(--app-danger)'
              : undefined;

    const current = formatAmount(progress.current, progress.unit);
    const total = formatAmount(progress.total, progress.unit);
    const counter = current && total ? `${current} / ${total}` : current || total;

    return (
        <div className={compact ? 'min-w-[180px]' : 'space-y-2'}>
            <div className="flex items-center justify-between gap-3 text-xs">
                <span className="font-semibold text-[var(--app-text-primary)]">
                    {phaseTextMap[progress.phase] || progress.phase}
                </span>
                <span className="text-[var(--app-text-muted)]">
                    {Math.round(progress.percent)}%
                </span>
            </div>
            <Progress
                percent={Math.round(progress.percent)}
                status={status}
                strokeColor={strokeColor}
                size={compact ? 'small' : 'default'}
                showInfo={false}
                strokeLinecap="round"
            />
            <div className="space-y-1">
                <Typography.Text className="text-xs !text-[var(--app-text-muted)]">
                    {progress.detail || '等待进度更新'}
                </Typography.Text>
                {counter && (
                    <div className="text-[11px] text-[var(--app-text-muted)]">
                        {counter}
                    </div>
                )}
            </div>
        </div>
    );
};

export default GalleryProgressPanel;
