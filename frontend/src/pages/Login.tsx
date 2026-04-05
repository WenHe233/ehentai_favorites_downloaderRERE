import React, { useState } from 'react';
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd';
import {
    ApiOutlined,
    LockOutlined,
    UserOutlined,
} from '@ant-design/icons';
import axios from 'axios';
import ApiConnectionSettings from '../components/ApiConnectionSettings';
import { buildApiUrl, useApiBaseUrl } from '../lib/api';
import { setAuthToken } from '../lib/auth';
import AppBrandIcon from '../components/AppBrandIcon';
import ThemeToggle from '../components/ThemeToggle';

interface LoginFormValues {
    username: string;
    password: string;
}

interface LoginResponse {
    auth_enabled: boolean;
    access_token: string | null;
    token_type: string;
    username: string;
}

interface LoginProps {
    onLoginSuccess: () => void;
}

const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
    const apiBaseUrl = useApiBaseUrl();
    const [loading, setLoading] = useState(false);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    const handleLogin = async (values: LoginFormValues) => {
        setLoading(true);
        setErrorMessage(null);

        try {
            const response = await axios.post<LoginResponse>(
                buildApiUrl('/auth/login', apiBaseUrl),
                values,
                { timeout: 10000 }
            );

            if (!response.data.auth_enabled) {
                message.info('当前未启用登录保护');
                onLoginSuccess();
                return;
            }

            if (!response.data.access_token) {
                setErrorMessage('后端没有返回有效令牌');
                return;
            }

            setAuthToken(response.data.access_token);
            onLoginSuccess();
        } catch (error) {
            if (axios.isAxiosError(error)) {
                setErrorMessage(error.response?.data?.detail || '登录失败');
            } else {
                setErrorMessage('登录失败');
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="login-screen">
            <div className="login-screen__toolbar">
                <ApiConnectionSettings
                    buttonText="连接设置"
                    buttonType="default"
                    buttonSize="middle"
                    onSaved={() => setErrorMessage(null)}
                />
                <ThemeToggle />
            </div>

            <div className="login-screen__panel">
                <div className="login-screen__hero">
                    <div className="login-screen__mark">
                        <AppBrandIcon size={52} />
                    </div>
                    <div>
                        <Typography.Title level={2} className="!mb-2 !text-[var(--app-text-primary)]">
                            EFDRR 控制台
                        </Typography.Title>
                        <Typography.Paragraph className="!mb-0 !text-[var(--app-text-muted)]">
                            进入 ehentai_favorites_downloaderRERE 后，你可以查看同步状态、实时下载进度、任务告警和系统配置。
                        </Typography.Paragraph>
                    </div>
                </div>

                <Card className="login-screen__card" bordered={false}>
                    <Typography.Title level={3} className="!mb-2">
                        管理员登录
                    </Typography.Title>
                    <Typography.Paragraph type="secondary">
                        如果你在 <code>config.yaml</code> 中启用了 <code>security.enable_auth</code>，
                        请使用管理员账号密码登录。
                    </Typography.Paragraph>
                    <div className="login-screen__api-hint">
                        <Typography.Text type="secondary">
                            <ApiOutlined style={{ marginRight: 8 }} />
                            当前后端地址：<code>{apiBaseUrl}</code>
                        </Typography.Text>
                    </div>

                    {errorMessage && (
                        <Alert
                            type="error"
                            showIcon
                            message="登录失败"
                            description={errorMessage}
                            style={{ marginBottom: 16 }}
                        />
                    )}

                    <Form layout="vertical" onFinish={handleLogin} size="large">
                        <Form.Item
                            label="用户名"
                            name="username"
                            rules={[{ required: true, message: '请输入用户名' }]}
                        >
                            <Input autoComplete="username" prefix={<UserOutlined />} />
                        </Form.Item>
                        <Form.Item
                            label="密码"
                            name="password"
                            rules={[{ required: true, message: '请输入密码' }]}
                        >
                            <Input.Password autoComplete="current-password" prefix={<LockOutlined />} />
                        </Form.Item>
                        <Button type="primary" htmlType="submit" block loading={loading}>
                            进入控制台
                        </Button>
                    </Form>
                </Card>
            </div>
        </div>
    );
};

export default Login;
