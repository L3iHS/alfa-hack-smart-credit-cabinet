import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type MutableRefObject,
} from "react";
import { useNavigate } from "react-router-dom";
import { api, setCsrf, setIdentity, errorMessage } from "../api/client";
import type { Recovery, User } from "../api/types";

interface Session {
  user: User | null;
  loading: boolean;
  error: string;
  expired: boolean;
  refresh: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  recovery: MutableRefObject<Recovery | null>;
}
const Context = createContext<Session | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expired, setExpired] = useState(false);
  const recovery = useRef<Recovery | null>(null);
  const navigate = useNavigate();
  function refresh() {
    setLoading(true);
    setError("");
    api<User>("/me")
      .then((value) => {
        setIdentity(value);
        setUser(value);
      })
      .catch((error) => {
        if (error.status !== 401) setError(errorMessage(error));
      })
      .finally(() => setLoading(false));
  }
  useEffect(refresh, []);
  useEffect(() => {
    const listener = () => {
      setIdentity(null);
      setUser(null);
      setExpired(true);
      navigate("/login", { replace: true });
    };
    window.addEventListener("session-expired", listener);
    return () => window.removeEventListener("session-expired", listener);
  }, [navigate]);
  async function login(email: string, password: string) {
    const result = await api<{ user: User; csrf_token: string }>(
      "/auth/login",
      { method: "POST", body: { email, password } },
    );
    const restore = recovery.current?.owner === result.user.id;
    if (!restore) recovery.current = null;
    setCsrf(result.csrf_token);
    setIdentity(result.user);
    setUser(result.user);
    setExpired(false);
    navigate(
      restore
        ? recovery.current!.path
        : result.user.role === "staff"
          ? "/staff/applications"
          : "/applications",
      { replace: true },
    );
  }
  async function logout() {
    await api("/auth/logout", { method: "POST" });
    recovery.current = null;
    setCsrf(null);
    setIdentity(null);
    setUser(null);
    setExpired(false);
    navigate("/login", { replace: true });
  }
  return (
    <Context.Provider
      value={{
        user,
        loading,
        error,
        expired,
        refresh,
        login,
        logout,
        recovery,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useSession() {
  return useContext(Context)!;
}
