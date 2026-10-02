import { lazy, Suspense, useEffect, useState } from "react";
import axios from "axios";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SWRConfig } from "swr";
import api, { buildApiUrl, useApiBaseUrl } from "@/lib/api";
import { clearAuthToken, getAuthToken } from "@/lib/auth";
import { Loading, ErrorPanel } from "@/components/common";
import ApiConnectionSettings from "@/components/ApiConnectionSettings";
const AppLayout = lazy(() => import("@/components/AppLayout"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Galleries = lazy(() => import("@/pages/Galleries"));
const Settings = lazy(() => import("@/pages/Settings"));
const Login = lazy(() => import("@/pages/Login"));
function Connection({ base }: { base: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    enabled: boolean;
    authenticated: boolean;
    error?: unknown;
  }>({ loading: true, enabled: false, authenticated: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    async function load() {
      try {
        const { data } = await axios.get(buildApiUrl("/auth/config", base), {
          signal: controller.signal,
          timeout: 10000,
        });
        let authenticated = !data.auth_enabled;
        if (data.auth_enabled && getAuthToken()) {
          try {
            await api.get("/auth/me", { signal: controller.signal });
            authenticated = true;
          } catch (error) {
            if (axios.isAxiosError(error) && error.response?.status === 401)
              clearAuthToken();
            else throw error;
          }
        }
        if (active)
          setState({
            loading: false,
            enabled: data.auth_enabled,
            authenticated,
          });
      } catch (error) {
        if (active)
          setState({
            loading: false,
            enabled: false,
            authenticated: false,
            error,
          });
      }
    }
    void load();
    const unauthorized = () =>
      setState((current) => ({ ...current, authenticated: false }));
    window.addEventListener("auth:unauthorized", unauthorized);
    return () => {
      active = false;
      controller.abort();
      window.removeEventListener("auth:unauthorized", unauthorized);
    };
  }, [base, attempt]);
  if (state.loading) return <Loading />;
  if (state.error)
    return (
      <div className="mx-auto max-w-lg space-y-6 px-6 py-24">
        <h1 className="page-heading">无法连接后端</h1>
        <ErrorPanel
          error={state.error}
          retry={() => setAttempt((value) => value + 1)}
        />
        <ApiConnectionSettings
          onSaved={() => setAttempt((value) => value + 1)}
        />
      </div>
    );
  const needsLogin = state.enabled && !state.authenticated;
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route
            path="/login"
            element={
              needsLogin ? (
                <Login
                  onLoginSuccess={() =>
                    setState((current) => ({ ...current, authenticated: true }))
                  }
                />
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/"
            element={
              needsLogin ? (
                <Navigate to="/login" replace />
              ) : (
                <AppLayout
                  authEnabled={state.enabled}
                  onLogout={() => {
                    clearAuthToken();
                    setState((current) => ({
                      ...current,
                      authenticated: false,
                    }));
                  }}
                />
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
}
export default function App() {
  const base = useApiBaseUrl();
  return (
    <SWRConfig
      key={base}
      value={{ provider: () => new Map(), shouldRetryOnError: false }}
    >
      <Connection key={base} base={base} />
    </SWRConfig>
  );
}
