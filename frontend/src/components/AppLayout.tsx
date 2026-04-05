import React, { useEffect, useMemo, useState } from 'react';
import { Button, Layout, Menu, Skeleton } from 'antd';
import {
    DashboardOutlined,
    LogoutOutlined,
    PictureOutlined,
    SettingOutlined,
} from '@ant-design/icons';
import { Link, Outlet, useLocation } from 'react-router-dom';
import api from '../lib/api';
import AppBrandIcon from './AppBrandIcon';
import ThemeToggle from './ThemeToggle';
import { useAppTheme } from '../lib/theme';

const { Sider, Content, Footer } = Layout;

interface AppLayoutProps {
    authEnabled: boolean;
    onLogout: () => void;
}

interface StatusSummary {
    downloader_running: boolean;
    queue_len: number;
    active_downloads: number;
    sync_running: boolean;
}

const AppLayout: React.FC<AppLayoutProps> = ({ authEnabled, onLogout }) => {
    const [collapsed, setCollapsed] = useState(false);
    const [status, setStatus] = useState<StatusSummary | null>(null);
    const location = useLocation();
    const { resolvedMode } = useAppTheme();

    useEffect(() => {
        let isMounted = true;

        const fetchStatus = async () => {
            try {
                const response = await api.get<StatusSummary>('/status');
                if (isMounted) {
                    setStatus(response.data);
                }
            } catch (error) {
                console.error(error);
            }
        };

        void fetchStatus();
        const timer = window.setInterval(() => {
            void fetchStatus();
        }, 25000);

        return () => {
            isMounted = false;
            window.clearInterval(timer);
        };
    }, []);

    const menuItems = useMemo(
        () => [
            {
                key: '/',
                icon: <DashboardOutlined />,
                label: <Link to="/">仪表盘</Link>,
            },
            {
                key: '/galleries',
                icon: <PictureOutlined />,
                label: <Link to="/galleries">任务中心</Link>,
            },
            {
                key: '/settings',
                icon: <SettingOutlined />,
                label: <Link to="/settings">系统设置</Link>,
            },
        ],
        []
    );

    const sidebarMetrics = [
        {
            label: '下载器',
            value: status ? (status.downloader_running ? '在线' : '离线') : '...',
        },
        {
            label: '同步',
            value: status ? (status.sync_running ? '运行中' : '空闲') : '...',
        },
        {
            label: '活跃任务',
            value: status ? `${status.active_downloads}` : '...',
        },
        {
            label: '等待队列',
            value: status ? `${status.queue_len}` : '...',
        },
    ];

    return (
        <Layout className="app-shell">
            <Sider
                className="app-shell__sider"
                collapsible
                width={280}
                collapsedWidth={88}
                collapsed={collapsed}
                onCollapse={(value) => setCollapsed(value)}
                theme={resolvedMode === 'dark' ? 'dark' : 'light'}
            >
                <div className="app-shell__brand">
                    <div className="app-shell__brand-mark">
                        <AppBrandIcon size={52} />
                    </div>
                    {!collapsed && (
                        <div>
                            <div className="app-shell__brand-title">EFDRR</div>
                            <div className="app-shell__brand-subtitle">ehentai_favorites_downloaderRERE</div>
                        </div>
                    )}
                </div>

                {!collapsed && (
                    <div className="app-shell__brand-panel">
                        {status ? (
                            <div className="app-shell__metrics-grid">
                                {sidebarMetrics.map((metric) => (
                                    <div key={metric.label} className="app-shell__metric-chip">
                                        <span>{metric.label}</span>
                                        <strong>{metric.value}</strong>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <Skeleton active paragraph={{ rows: 2 }} title={false} />
                        )}
                    </div>
                )}

                <Menu
                    className="app-shell__menu"
                    mode="inline"
                    selectedKeys={[location.pathname]}
                    items={menuItems}
                    theme={resolvedMode === 'dark' ? 'dark' : 'light'}
                />

                <div className="app-shell__sidebar-footer">
                    <div className="app-shell__sidebar-actions">
                        <ThemeToggle compact={collapsed} />
                        {authEnabled && (
                            <Button type="text" icon={<LogoutOutlined />} onClick={onLogout}>
                                {!collapsed && '退出登录'}
                            </Button>
                        )}
                    </div>
                    {!collapsed && <div className="app-shell__sidebar-version">v1.0.0</div>}
                </div>
            </Sider>

            <Layout className="app-shell__main">
                <Content className="app-shell__content">
                    <div className="app-shell__panel">
                        <Outlet />
                    </div>
                </Content>

                <Footer className="app-shell__footer">
                    ehentai_favorites_downloaderRERE ©{new Date().getFullYear()} · EFDRR 控制台
                </Footer>
            </Layout>
        </Layout>
    );
};

export default AppLayout;
