import { useEffect, useState } from 'react';
import axios from 'axios';
import { clearAuthToken, getAuthToken, notifyAuthUnauthorized } from './auth';

const API_BASE_URL_STORAGE_KEY = 'efdrr.api-base-url';
const DEFAULT_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '') || '/api/v1';
const apiBaseUrlListeners = new Set<(value: string) => void>();

const readStoredApiBaseUrl = () => {
    if (typeof window === 'undefined') {
        return null;
    }

    const raw = window.localStorage.getItem(API_BASE_URL_STORAGE_KEY)?.trim();
    return raw ? raw.replace(/\/+$/, '') || '/' : null;
};

let runtimeApiBaseUrl = readStoredApiBaseUrl() || DEFAULT_API_BASE_URL;

const notifyApiBaseUrlChange = () => {
    apiBaseUrlListeners.forEach((listener) => listener(runtimeApiBaseUrl));
    if (typeof window !== 'undefined') {
        window.dispatchEvent(
            new CustomEvent('api:base-url-changed', {
                detail: { apiBaseUrl: runtimeApiBaseUrl },
            })
        );
    }
};

export const getDefaultApiBaseUrl = () => DEFAULT_API_BASE_URL;
export const getApiBaseUrl = () => runtimeApiBaseUrl;
export const isCustomApiBaseUrl = () => runtimeApiBaseUrl !== DEFAULT_API_BASE_URL;

export const buildApiUrl = (path: string, baseUrl = getApiBaseUrl()) => {
    const normalizedBase = baseUrl.replace(/\/+$/, '');
    return `${normalizedBase}${path.startsWith('/') ? path : `/${path}`}`;
};

const api = axios.create({
    baseURL: runtimeApiBaseUrl,
    timeout: 10000,
});

export const setApiBaseUrl = (value: string) => {
    const normalized = value.trim().replace(/\/+$/, '') || DEFAULT_API_BASE_URL;
    runtimeApiBaseUrl = normalized;

    if (typeof window !== 'undefined') {
        if (normalized === DEFAULT_API_BASE_URL) {
            window.localStorage.removeItem(API_BASE_URL_STORAGE_KEY);
        } else {
            window.localStorage.setItem(API_BASE_URL_STORAGE_KEY, normalized);
        }
    }

    api.defaults.baseURL = normalized;
    notifyApiBaseUrlChange();
    return normalized;
};

export const resetApiBaseUrl = () => {
    runtimeApiBaseUrl = DEFAULT_API_BASE_URL;
    if (typeof window !== 'undefined') {
        window.localStorage.removeItem(API_BASE_URL_STORAGE_KEY);
    }
    api.defaults.baseURL = runtimeApiBaseUrl;
    notifyApiBaseUrlChange();
    return runtimeApiBaseUrl;
};

export const subscribeApiBaseUrl = (listener: (value: string) => void) => {
    apiBaseUrlListeners.add(listener);
    return () => {
        apiBaseUrlListeners.delete(listener);
    };
};

export const useApiBaseUrl = () => {
    const [apiBaseUrl, setApiBaseUrlState] = useState(getApiBaseUrl());

    useEffect(() => subscribeApiBaseUrl(setApiBaseUrlState), []);

    return apiBaseUrl;
};

api.interceptors.request.use((config) => {
    const token = getAuthToken();
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            clearAuthToken();
            notifyAuthUnauthorized();
        }
        return Promise.reject(error);
    }
);

export default api;
