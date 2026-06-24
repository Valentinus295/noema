import { useEffect, useRef, useCallback, useState } from 'react';
import type { WsMessage } from '@/types';

interface UseWebSocketOptions {
  onMessage: (msg: WsMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: Event) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  reconnectAttempt: number;
  send: (data: unknown) => void;
  disconnect: () => void;
}

export function useWebSocket(
  url: string,
  options: UseWebSocketOptions,
): UseWebSocketReturn {
  const {
    onMessage,
    onOpen,
    onClose,
    onError,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (reconnectCountRef.current >= maxReconnectAttempts) {
      console.warn('[WS] Max reconnect attempts reached');
      return;
    }

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        reconnectCountRef.current = 0;
        setReconnectAttempt(0);
        onOpen?.();
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg: WsMessage = JSON.parse(event.data);
          onMessage(msg);
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      ws.onclose = (event) => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        wsRef.current = null;
        onClose?.();

        // Don't reconnect if closed cleanly by client
        if (event.code === 1000) return;

        reconnectCountRef.current += 1;
        setReconnectAttempt(reconnectCountRef.current);
        console.warn(`[WS] Disconnected, reconnecting in ${reconnectInterval}ms (attempt ${reconnectCountRef.current})`);
        reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
      };

      ws.onerror = (err) => {
        if (!mountedRef.current) return;
        console.error('[WS] Error:', err);
        onError?.(err);
      };
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err);
      reconnectCountRef.current += 1;
      setReconnectAttempt(reconnectCountRef.current);
      reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
    }
  }, [url, onMessage, onOpen, onClose, onError, reconnectInterval, maxReconnectAttempts]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const disconnect = useCallback(() => {
    mountedRef.current = false;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmount');
      }
    };
  }, [connect]);

  return { isConnected, reconnectAttempt, send, disconnect };
}
