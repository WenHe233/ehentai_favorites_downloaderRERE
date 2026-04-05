import React, { useEffect, useState } from 'react';
import { ApiOutlined, CheckCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Input, Modal, Space, Typography, message } from 'antd';
import axios from 'axios';
import type { ButtonProps } from 'antd';
import {
    buildApiUrl,
    getDefaultApiBaseUrl,
    isCustomApiBaseUrl,
    resetApiBaseUrl,
    setApiBaseUrl,
    useApiBaseUrl,
} from '../lib/api';

interface AuthConfigResponse {
    auth_enabled: boolean;
}

interface ApiConnectionSettingsProps {
    buttonText?: string;
    buttonType?: ButtonProps['type'];
    buttonSize?: ButtonProps['size'];
    ghost?: boolean;
    className?: string;
    onSaved?: (nextApiBaseUrl: string) => void;
}

const validateApiBaseUrl = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) {
        return '后端地址不能为空';
    }
    if (/^https?:\/\//i.test(trimmed)) {
        return null;
    }
    if (trimmed.startsWith('/')) {
        return null;
    }
    return '后端地址必须以 http://、https:// 或 / 开头';
};

const ApiConnectionSettings: React.FC<ApiConnectionSettingsProps> = ({
    buttonText = '连接设置',
    buttonType = 'default',
    buttonSize = 'middle',
    ghost = false,
    className,
    onSaved,
}) => {
    const currentApiBaseUrl = useApiBaseUrl();
    const [open, setOpen] = useState(false);
    const [draftApiBaseUrl, setDraftApiBaseUrl] = useState(currentApiBaseUrl);
    const [testing, setTesting] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (open) {
            setDraftApiBaseUrl(currentApiBaseUrl);
        }
    }, [currentApiBaseUrl, open]);

    const handleTest = async () => {
        const validationError = validateApiBaseUrl(draftApiBaseUrl);
        if (validationError) {
            message.error(validationError);
            return;
        }

        setTesting(true);
        try {
            const normalizedApiBaseUrl = draftApiBaseUrl.trim().replace(/\/+$/, '') || getDefaultApiBaseUrl();
            const response = await axios.get<AuthConfigResponse>(buildApiUrl('/auth/config', normalizedApiBaseUrl), {
                timeout: 8000,
            });
            const authLabel = response.data.auth_enabled ? '已开启登录保护' : '未开启登录保护';
            message.success(`连接成功：${normalizedApiBaseUrl}（${authLabel}）`);
        } catch (error) {
            if (axios.isAxiosError(error)) {
                message.error(error.response?.data?.detail || `连接失败：${error.message}`);
            } else {
                message.error('连接失败');
            }
        } finally {
            setTesting(false);
        }
    };

    const handleSave = async () => {
        const validationError = validateApiBaseUrl(draftApiBaseUrl);
        if (validationError) {
            message.error(validationError);
            return;
        }

        setSaving(true);
        try {
            const nextApiBaseUrl = setApiBaseUrl(draftApiBaseUrl);
            message.success('后端地址已保存，新的请求会使用这个地址');
            onSaved?.(nextApiBaseUrl);
            setOpen(false);
        } finally {
            setSaving(false);
        }
    };

    const handleReset = () => {
        const nextApiBaseUrl = resetApiBaseUrl();
        setDraftApiBaseUrl(nextApiBaseUrl);
        message.success('已恢复为默认后端地址');
        onSaved?.(nextApiBaseUrl);
    };

    return (
        <>
            <Button
                icon={<ApiOutlined />}
                type={buttonType}
                size={buttonSize}
                ghost={ghost}
                className={className}
                onClick={() => setOpen(true)}
            >
                {buttonText}
            </Button>
            <Modal
                title="连接设置"
                open={open}
                onCancel={() => setOpen(false)}
                footer={[
                    <Button key="reset" icon={<ReloadOutlined />} onClick={handleReset}>
                        恢复默认
                    </Button>,
                    <Button key="test" onClick={handleTest} loading={testing}>
                        测试连接
                    </Button>,
                    <Button key="save" type="primary" onClick={handleSave} loading={saving}>
                        保存地址
                    </Button>,
                ]}
            >
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                    <Alert
                        type="info"
                        showIcon
                        message="默认情况下，前端会通过同源 /api/v1 访问后端。只有当前后端不在同一地址时，才需要手动修改。"
                    />
                    <div className="api-connection-summary">
                        <div>
                            <div className="api-connection-summary__label">当前后端地址</div>
                            <code>{currentApiBaseUrl}</code>
                        </div>
                        <div>
                            <div className="api-connection-summary__label">地址来源</div>
                            <Typography.Text type="secondary">
                                {isCustomApiBaseUrl() ? '已自定义' : '默认配置'}
                            </Typography.Text>
                        </div>
                    </div>
                    <div>
                        <Typography.Text strong>后端地址</Typography.Text>
                        <Input
                            value={draftApiBaseUrl}
                            onChange={(event) => setDraftApiBaseUrl(event.target.value)}
                            placeholder={getDefaultApiBaseUrl()}
                            style={{ marginTop: 8 }}
                        />
                        <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}>
                            支持完整地址，例如 <code>http://192.168.1.100:8000/api/v1</code>，
                            也支持同源路径，例如 <code>/api/v1</code>。
                        </Typography.Paragraph>
                    </div>
                    <div className="console-note">
                        <CheckCircleOutlined style={{ marginRight: 8 }} />
                        保存后，登录、列表、SSE 和后续请求都会切换到新的后端地址。
                    </div>
                </Space>
            </Modal>
        </>
    );
};

export default ApiConnectionSettings;
