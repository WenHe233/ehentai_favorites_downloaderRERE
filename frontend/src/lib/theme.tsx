/* eslint-disable react-refresh/only-export-components */
import React, {
    createContext,
    useContext,
    useEffect,
    useLayoutEffect,
    useMemo,
    useState,
} from 'react';
import { App as AntApp, ConfigProvider, theme as antTheme } from 'antd';

export type ThemeMode = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'eh_theme_mode';

interface ThemeContextValue {
    mode: ThemeMode;
    resolvedMode: ResolvedTheme;
    setMode: (mode: ThemeMode) => void;
    toggleMode: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const getStoredThemeMode = (): ThemeMode => {
    if (typeof window === 'undefined') {
        return 'system';
    }

    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
};

const getSystemTheme = (): ResolvedTheme => {
    if (typeof window === 'undefined') {
        return 'light';
    }

    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const applyThemeToDocument = (mode: ThemeMode, resolvedMode: ResolvedTheme) => {
    if (typeof document === 'undefined') {
        return;
    }

    const targets = [document.documentElement, document.body].filter(
        (element): element is HTMLElement => Boolean(element)
    );

    for (const target of targets) {
        target.dataset.theme = resolvedMode;
        target.dataset.themeMode = mode;
        target.style.colorScheme = resolvedMode;
        target.classList.toggle('theme-dark', resolvedMode === 'dark');
        target.classList.toggle('theme-light', resolvedMode === 'light');
    }
};

export const bootstrapTheme = () => {
    const mode = getStoredThemeMode();
    const resolvedMode = mode === 'system' ? getSystemTheme() : mode;
    applyThemeToDocument(mode, resolvedMode);
    return { mode, resolvedMode };
};

const lightTokens = {
    colorPrimary: '#2563eb',
    colorSuccess: '#15803d',
    colorWarning: '#d97706',
    colorError: '#dc2626',
    colorInfo: '#4f46e5',
    colorBgBase: '#f4f7fb',
    colorBgLayout: '#eef3f8',
    colorBgContainer: '#ffffff',
    colorBorder: '#d8e1ec',
    colorText: '#112033',
    colorTextSecondary: '#516072',
    colorFillSecondary: '#edf2f7',
    borderRadius: 18,
    borderRadiusLG: 24,
    fontFamily: '"IBM Plex Sans", "Segoe UI", "PingFang SC", sans-serif',
    boxShadowSecondary: '0 18px 50px rgba(15, 23, 42, 0.08)',
};

const darkTokens = {
    colorPrimary: '#60a5fa',
    colorSuccess: '#4ade80',
    colorWarning: '#fbbf24',
    colorError: '#fb7185',
    colorInfo: '#818cf8',
    colorBgBase: '#09111b',
    colorBgLayout: '#070d15',
    colorBgContainer: '#0f1a27',
    colorBorder: '#203041',
    colorText: '#ecf3fb',
    colorTextSecondary: '#9fb1c7',
    colorFillSecondary: '#132233',
    borderRadius: 18,
    borderRadiusLG: 24,
    fontFamily: '"IBM Plex Sans", "Segoe UI", "PingFang SC", sans-serif',
    boxShadowSecondary: '0 22px 55px rgba(2, 8, 23, 0.5)',
};

const componentTheme = {
    Card: {
        headerHeight: 56,
    },
    Button: {
        controlHeight: 42,
        controlHeightLG: 48,
        fontWeight: 600,
    },
    Input: {
        controlHeight: 44,
    },
    InputNumber: {
        controlHeight: 44,
    },
    Select: {
        controlHeight: 44,
    },
    Menu: {
        itemHeight: 48,
        itemBorderRadius: 14,
    },
    Table: {
        headerBorderRadius: 14,
    },
};

export const ThemeProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
    const [mode, setMode] = useState<ThemeMode>(getStoredThemeMode);
    const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme);

    useEffect(() => {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const onChange = (event: MediaQueryListEvent) => {
            setSystemTheme(event.matches ? 'dark' : 'light');
        };

        mediaQuery.addEventListener('change', onChange);
        return () => {
            mediaQuery.removeEventListener('change', onChange);
        };
    }, []);

    useEffect(() => {
        window.localStorage.setItem(THEME_STORAGE_KEY, mode);
    }, [mode]);

    const resolvedMode = mode === 'system' ? systemTheme : mode;

    useLayoutEffect(() => {
        applyThemeToDocument(mode, resolvedMode);
    }, [mode, resolvedMode]);

    const contextValue = useMemo<ThemeContextValue>(
        () => ({
            mode,
            resolvedMode,
            setMode,
            toggleMode: () => setMode((current) => (current === 'dark' ? 'light' : 'dark')),
        }),
        [mode, resolvedMode]
    );

    const antdTheme = useMemo(
        () => ({
            algorithm: resolvedMode === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
            token: resolvedMode === 'dark' ? darkTokens : lightTokens,
            components: componentTheme,
        }),
        [resolvedMode]
    );

    return (
        <ThemeContext.Provider value={contextValue}>
            <ConfigProvider theme={antdTheme}>
                <AntApp>{children}</AntApp>
            </ConfigProvider>
        </ThemeContext.Provider>
    );
};

export const useAppTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) {
        throw new Error('useAppTheme must be used within ThemeProvider');
    }
    return context;
};
