import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type MutableRefObject,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, setCsrf, setIdentity, errorMessage } from "../api/client";
import type { Recovery, User } from "../api/types";

interface Session {
  user: User | null;
  loading: boolean;
  error: string;
  expired: boolean;
  loginPath: string | null;
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
  const [loginPath, setLoginPath] = useState<string | null>(null);
  const recovery = useRef<Recovery | null>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const resume = useRef<{ owner: string; path: string } | null>(null);
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
      if (user) resume.current = { owner: user.id, path: pathname };
      setIdentity(null);
      setUser(null);
      setExpired(true);
      setLoginPath(null);
      navigate("/login", { replace: true });
    };
    window.addEventListener("session-expired", listener);
    return () => window.removeEventListener("session-expired", listener);
  }, [navigate, pathname, user]);
  async function login(email: string, password: string) {
    const result = await api<{ user: User; csrf_token: string }>(
      "/auth/login",
      { method: "POST", body: { email, password } },
    );
    const restore = recovery.current?.owner === result.user.id;
    const returnPath =
      resume.current?.owner === result.user.id ? resume.current.path : null;
    resume.current = null;
    if (!restore) recovery.current = null;
    setIdentity(result.user);
    setCsrf(result.csrf_token, result.user.id);
    setUser(result.user);
    setExpired(false);
    const destination = restore
      ? recovery.current!.path
      : returnPath ||
        (result.user.role === "staff"
          ? "/staff/applications"
          : "/applications");
    setLoginPath(destination);
    navigate(destination, { replace: true });
  }
  async function logout() {
    await api("/auth/logout", { method: "POST" });
    recovery.current = null;
    resume.current = null;
    setLoginPath(null);
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
        loginPath,
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
