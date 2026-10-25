import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

type Notice = { message: string; error: boolean };
const ToastContext = createContext<(message: string, error?: boolean) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const show = useCallback((message: string, error = false) => {
    setNotice({ message, error });
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), notice.error ? 5000 : 3000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toast-region" role="status" aria-atomic="true">
        {notice && <div className={`toast${notice.error ? " toast-error" : ""}`}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" stroke="currentColor" strokeWidth="2">
            {notice.error ? <path d="M12 4v10m0 4v2" /> : <path d="m5 12 4 4L19 6" />}
          </svg>
          <span>{notice.message}</span>
        </div>}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
