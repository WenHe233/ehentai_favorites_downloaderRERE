import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Alert, Button, Space, Spin, Typography } from 'antd';
import axios from 'axios';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import ApiConnectionSettings from './components/ApiConnectionSettings';
import api, { buildApiUrl, useApiBaseUrl } from './lib/api';
import { clearAuthToken, getAuthToken } from './lib/auth';

const AppLayout = lazy(() => import('./components/AppLayout'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Galleries = lazy(() => import('./pages/Galleries'));
const Login = lazy(() => import('./pages/Login'));
const Settings = lazy(() => import('./pages/Settings'));

interface AuthConfigResponse {
  auth_enabled: boolean;
}

const fullscreenSpinner = (
  <div className="min-h-screen flex items-center justify-center">
    <Spin size="large" />
  </div>
);

const routeSpinner = (
  <div className="min-h-[240px] flex items-center justify-center">
    <Spin size="large" />
  </div>
);

const App: React.FC = () => {
  const apiBaseUrl = useApiBaseUrl();
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const bootstrapAuth = useCallback(async () => {
    setLoading(true);
    setConnectionError(null);

    try {
      const response = await axios.get<AuthConfigResponse>(buildApiUrl('/auth/config', apiBaseUrl), {
        timeout: 10000,
      });

      const enabled = Boolean(response.data.auth_enabled);
      setAuthEnabled(enabled);

      if (!enabled) {
        setAuthenticated(true);
        return;
      }

      if (!getAuthToken()) {
        setAuthenticated(false);
        return;
      }

      try {
        await api.get('/auth/me');
        setAuthenticated(true);
      } catch {
        clearAuthToken();
        setAuthenticated(false);
      }
    } catch (error) {
      setAuthEnabled(false);
      setAuthenticated(false);
      if (axios.isAxiosError(error)) {
        setConnectionError(error.response?.data?.detail || error.message || '无法连接到后端服务');
      } else {
        setConnectionError('无法连接到后端服务');
      }
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    void bootstrapAuth();

    const onUnauthorized = () => {
      setAuthenticated(false);
    };

    window.addEventListener('auth:unauthorized', onUnauthorized);
    return () => {
      window.removeEventListener('auth:unauthorized', onUnauthorized);
    };
  }, [bootstrapAuth]);

  const handleLogout = () => {
    clearAuthToken();
    setAuthenticated(false);
  };

  if (loading) {
    return fullscreenSpinner;
  }

  if (connectionError) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div style={{ width: '100%', maxWidth: 560 }}>
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            <Typography.Title level={2} style={{ margin: 0 }}>
              无法连接后端
            </Typography.Title>
            <Alert
              type="error"
              showIcon
              message="当前前端无法连接到后端服务"
              description={connectionError}
            />
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              请检查后端是否已启动，或在“连接设置”中修改正确的后端地址。
            </Typography.Paragraph>
            <Space wrap>
              <ApiConnectionSettings buttonText="连接设置" onSaved={() => void bootstrapAuth()} />
              <Button onClick={() => void bootstrapAuth()}>重新检测</Button>
            </Space>
          </Space>
        </div>
      </div>
    );
  }

  const needsLogin = authEnabled && !authenticated;

  return (
    <BrowserRouter>
      <Suspense fallback={routeSpinner}>
        <Routes>
          {authEnabled && (
            <Route
              path="/login"
              element={
                authenticated ? (
                  <Navigate to="/" replace />
                ) : (
                  <Login onLoginSuccess={() => setAuthenticated(true)} />
                )
              }
            />
          )}
          <Route
            path="/"
            element={
              needsLogin ? (
                <Navigate to="/login" replace />
              ) : (
                <AppLayout authEnabled={authEnabled} onLogout={handleLogout} />
              )
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="galleries" element={<Galleries />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};

export default App;
