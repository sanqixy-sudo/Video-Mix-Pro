import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, AlertTriangle, X, Info } from "lucide-react";
import type { Toast, ToastTone } from "../types";

let showToastFn: ((tone: ToastTone, message: string) => void) | null = null;

export function showToast(tone: ToastTone, message: string) {
  showToastFn?.(tone, message);
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((tone: ToastTone, message: string) => {
    const id = Date.now().toString() + Math.random().toString(36).slice(2, 6);
    setToasts((prev) => [...prev, { id, tone, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  useEffect(() => {
    showToastFn = addToast;
    return () => { showToastFn = null; };
  }, [addToast]);

  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.tone}`}>
          {t.tone === "success" && <CheckCircle2 size={16} />}
          {t.tone === "warning" && <AlertTriangle size={16} />}
          {t.tone === "danger" && <X size={16} />}
          {t.tone === "info" && <Info size={16} />}
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
