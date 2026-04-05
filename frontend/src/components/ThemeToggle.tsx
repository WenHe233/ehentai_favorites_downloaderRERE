import React from 'react';
import { Dropdown, Button } from 'antd';
import {
    DesktopOutlined,
    MoonOutlined,
    SunOutlined,
} from '@ant-design/icons';
import { useAppTheme } from '../lib/theme';

interface ThemeToggleProps {
    compact?: boolean;
}

const ThemeToggle: React.FC<ThemeToggleProps> = ({ compact = false }) => {
    const { mode, resolvedMode, setMode } = useAppTheme();

    const icon =
        mode === 'system' ? (
            <DesktopOutlined />
        ) : resolvedMode === 'dark' ? (
            <MoonOutlined />
        ) : (
            <SunOutlined />
        );

    return (
        <Dropdown
            trigger={['click']}
            menu={{
                selectedKeys: [mode],
                items: [
                    {
                        key: 'system',
                        label: '跟随系统',
                        icon: <DesktopOutlined />,
                        onClick: () => setMode('system'),
                    },
                    {
                        key: 'light',
                        label: '浅色模式',
                        icon: <SunOutlined />,
                        onClick: () => setMode('light'),
                    },
                    {
                        key: 'dark',
                        label: '深色模式',
                        icon: <MoonOutlined />,
                        onClick: () => setMode('dark'),
                    },
                ],
            }}
        >
            <Button type="text" icon={icon}>
                {!compact && (mode === 'system' ? '系统' : resolvedMode === 'dark' ? '深色' : '浅色')}
            </Button>
        </Dropdown>
    );
};

export default ThemeToggle;
