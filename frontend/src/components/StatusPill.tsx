import React from 'react';

interface StatusPillProps {
    status: string;
}

const statusTextMap: Record<string, string> = {
    pending: '等待中',
    downloading: '下载中',
    completed: '已完成',
    partial: '部分完成',
    archived: '已归档',
    failed: '失败',
    outdated: '待更新',
    cancelled: '已取消',
};

const StatusPill: React.FC<StatusPillProps> = ({ status }) => {
    const normalized = status.toLowerCase();

    return (
        <span className={`status-pill status-pill--${normalized}`}>
            {statusTextMap[normalized] || status.toUpperCase()}
        </span>
    );
};

export default StatusPill;
