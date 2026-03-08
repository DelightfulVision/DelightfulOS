import { useEffect, useRef, useCallback } from "react";

export interface PiezoState {
  rms: number;
  baseline: number;
  peak: number;
  zcr: number;
}

export interface TapEvent {
  user: string;
  timestamp: number;
}

type TapCallback = (tap: TapEvent) => void;
type PiezoCallback = (state: PiezoState) => void;

export function usePiezo(onTap: TapCallback, onPiezo?: PiezoCallback) {
  const wsRef = useRef<WebSocket | null>(null);
  const onTapRef = useRef(onTap);
  const onPiezoRef = useRef(onPiezo);
  onTapRef.current = onTap;
  onPiezoRef.current = onPiezo;

  useEffect(() => {
    const host = window.location.hostname || "localhost";
    const url = `ws://${host}:8000/system/dashboard/ws`;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);

          // Piezo telemetry
          if (data.piezo && onPiezoRef.current) {
            for (const uid of Object.keys(data.piezo)) {
              const p = data.piezo[uid];
              onPiezoRef.current({
                rms: p.rms || 0,
                baseline: p.baseline || 0,
                peak: p.peak || 0,
                zcr: p.zcr || 0,
              });
            }
          }

          // Tap events from recent signals
          for (const s of data.recent_signals || []) {
            if (s.signal_type === "collar_tap" && s.age < 1.5) {
              onTapRef.current({
                user: s.source_user,
                timestamp: Date.now(),
              });
            }
          }
        } catch {}
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);
}
