import {
    useEffect,
    useEffectEvent,
    useMemo,
    useState,
} from 'react';
import {
    clearAuthToken,
    getAuthToken,
    notifyAuthUnauthorized,
} from './auth';
import { buildApiUrl, useApiBaseUrl } from './api';

export interface GalleryProgress {
    phase: 'queued' | 'preparing' | 'polling' | 'downloading' | 'packaging' | 'verifying' | 'completed' | 'partial' | 'failed' | 'cancelled';
    percent: number;
    current: number | null;
    total: number | null;
    unit: 'images' | 'bytes' | 'files' | null;
    detail: string;
    updated_at: string;
}

export interface GalleryProgressEvent {
    gid: number;
    title?: string;
    status?: string;
    error_msg?: string | null;
    downloaded_at?: string | null;
    requested_quality?: string | null;
    resolved_quality?: string | null;
    progress: GalleryProgress;
}

export interface SyncStatusEvent {
    sync_running: boolean;
    sync_last_error?: string | null;
    last_sync_ts?: string | null;
    updated_at: string;
}

export interface DownloadSnapshotEvent {
    active_galleries: GalleryProgressEvent[];
    sync_status: SyncStatusEvent;
    downloader_running: boolean;
    updated_at: string;
}

export type DownloadStreamConnectionState =
    | 'disconnected'
    | 'connecting'
    | 'connected'
    | 'reconnecting';

interface UseDownloadEventStreamOptions {
    enabled?: boolean;
    onSnapshot?: (payload: DownloadSnapshotEvent) => void;
    onGalleryProgress?: (payload: GalleryProgressEvent) => void;
    onGalleryStatus?: (payload: GalleryProgressEvent) => void;
    onSyncStatus?: (payload: SyncStatusEvent) => void;
    onReconnected?: () => void;
}

export const useDownloadEventStream = ({
    enabled = true,
    onSnapshot,
    onGalleryProgress,
    onGalleryStatus,
    onSyncStatus,
    onReconnected,
}: UseDownloadEventStreamOptions) => {
    const apiBaseUrl = useApiBaseUrl();
    const [connectionState, setConnectionState] = useState<DownloadStreamConnectionState>(
        enabled ? 'connecting' : 'disconnected'
    );

    const handleSnapshot = useEffectEvent((payload: DownloadSnapshotEvent) => {
        onSnapshot?.(payload);
    });
    const handleGalleryProgress = useEffectEvent((payload: GalleryProgressEvent) => {
        onGalleryProgress?.(payload);
    });
    const handleGalleryStatus = useEffectEvent((payload: GalleryProgressEvent) => {
        onGalleryStatus?.(payload);
    });
    const handleSyncStatus = useEffectEvent((payload: SyncStatusEvent) => {
        onSyncStatus?.(payload);
    });
    const handleReconnected = useEffectEvent(() => {
        onReconnected?.();
    });

    useEffect(() => {
        if (!enabled) {
            setConnectionState('disconnected');
            return;
        }

        let isActive = true;
        let reconnectTimer: number | undefined;
        let heartbeatTimer: number | undefined;
        let hasConnected = false;
        let reconnectAttempts = 0;
        let currentController: AbortController | null = null;

        const clearTimers = () => {
            if (reconnectTimer) {
                window.clearTimeout(reconnectTimer);
            }
            if (heartbeatTimer) {
                window.clearTimeout(heartbeatTimer);
            }
        };

        const resetHeartbeat = () => {
            if (heartbeatTimer) {
                window.clearTimeout(heartbeatTimer);
            }

            heartbeatTimer = window.setTimeout(() => {
                currentController?.abort();
            }, 35000);
        };

        const dispatchSseEvent = (eventName: string, rawPayload: string) => {
            resetHeartbeat();

            try {
                const payload = JSON.parse(rawPayload);
                if (eventName === 'snapshot') {
                    handleSnapshot(payload);
                    return;
                }
                if (eventName === 'gallery_progress') {
                    handleGalleryProgress(payload);
                    return;
                }
                if (eventName === 'gallery_status') {
                    handleGalleryStatus(payload);
                    return;
                }
                if (eventName === 'sync_status') {
                    handleSyncStatus(payload);
                }
            } catch (error) {
                console.error('Failed to parse SSE payload', error);
            }
        };

        const parseEventChunk = (chunk: string) => {
            const lines = chunk.split('\n');
            let eventName = 'message';
            const dataLines: string[] = [];

            for (const line of lines) {
                if (!line || line.startsWith(':')) {
                    continue;
                }

                if (line.startsWith('event:')) {
                    eventName = line.slice(6).trim();
                    continue;
                }

                if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).trimStart());
                }
            }

            if (dataLines.length > 0) {
                dispatchSseEvent(eventName, dataLines.join('\n'));
            }
        };

        const scheduleReconnect = () => {
            if (!isActive) {
                return;
            }

            const delay = Math.min(15000, 1000 * 2 ** Math.min(reconnectAttempts, 4));
            reconnectAttempts += 1;
            setConnectionState(hasConnected ? 'reconnecting' : 'connecting');
            reconnectTimer = window.setTimeout(() => {
                void connect(true);
            }, delay);
        };

        const connect = async (isReconnect: boolean) => {
            if (!isActive) {
                return;
            }

            clearTimers();
            currentController = new AbortController();
            setConnectionState(hasConnected ? 'reconnecting' : 'connecting');

            try {
                const headers: HeadersInit = {
                    Accept: 'text/event-stream',
                };
                const token = getAuthToken();
                if (token) {
                    headers.Authorization = `Bearer ${token}`;
                }

                const response = await fetch(buildApiUrl('/events/downloads', apiBaseUrl), {
                    headers,
                    cache: 'no-store',
                    signal: currentController.signal,
                });

                if (response.status === 401) {
                    clearAuthToken();
                    notifyAuthUnauthorized();
                    setConnectionState('disconnected');
                    return;
                }

                if (!response.ok || !response.body) {
                    throw new Error(`SSE connection failed: ${response.status}`);
                }

                reconnectAttempts = 0;
                setConnectionState('connected');
                resetHeartbeat();

                if (isReconnect && hasConnected) {
                    handleReconnected();
                }
                hasConnected = true;

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (isActive) {
                    const { done, value } = await reader.read();
                    if (done) {
                        break;
                    }

                    buffer += decoder.decode(value, { stream: true });

                    let boundaryIndex = buffer.indexOf('\n\n');
                    while (boundaryIndex !== -1) {
                        const rawChunk = buffer.slice(0, boundaryIndex).replace(/\r/g, '');
                        buffer = buffer.slice(boundaryIndex + 2);
                        if (rawChunk.trim()) {
                            parseEventChunk(rawChunk);
                        }
                        boundaryIndex = buffer.indexOf('\n\n');
                    }
                }

                throw new Error('SSE stream closed');
            } catch (error) {
                if (!isActive) {
                    return;
                }

                if ((error as Error).name === 'AbortError' && !currentController?.signal.aborted) {
                    return;
                }

                scheduleReconnect();
            }
        };

        void connect(false);

        return () => {
            isActive = false;
            clearTimers();
            currentController?.abort();
            setConnectionState('disconnected');
        };
    }, [
        enabled,
        apiBaseUrl,
    ]);

    return useMemo(
        () => ({
            connectionState,
            isConnected: connectionState === 'connected',
        }),
        [connectionState]
    );
};
