import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
} from "react-router-dom";
import { SessionProvider, useSession } from "./auth/session";
import AppShell from "./components/AppShell";
import { ErrorPanel, Loading } from "./components/shared";
import LoginPage from "./pages/LoginPage";
import ApplicationsPage from "./pages/ApplicationsPage";
import ApplicationFormPage from "./pages/ApplicationFormPage";
import ApplicationDetailsPage from "./pages/ApplicationDetailsPage";
import StaffApplicationsPage from "./pages/StaffApplicationsPage";
import "./styles.css";

function Protected({ role }: { role?: "client" | "staff" }) {
  const { user, loading, error, refresh } = useSession();
  if (loading) return <Loading />;
  if (error) return <ErrorPanel error={new Error(error)} retry={refresh} />;
  if (!user) return <Navigate to="/login" replace />;
  if (role && user.role !== role)
    return (
      <Navigate
        to={user.role === "staff" ? "/staff/applications" : "/applications"}
        replace
      />
    );
  return <Outlet />;
}
function Home() {
  const { user } = useSession();
  return (
    <Navigate
      to={user?.role === "staff" ? "/staff/applications" : "/applications"}
      replace
    />
  );
}
export default function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Protected />}>
            <Route element={<AppShell />}>
              <Route index element={<Home />} />
              <Route element={<Protected role="client" />}>
                <Route path="/applications" element={<ApplicationsPage />} />
                <Route
                  path="/applications/new"
                  element={<ApplicationFormPage />}
                />
                <Route
                  path="/applications/:id"
                  element={<ApplicationDetailsPage />}
                />
                <Route
                  path="/applications/:id/edit"
                  element={<ApplicationFormPage />}
                />
              </Route>
              <Route element={<Protected role="staff" />}>
                <Route
                  path="/staff/applications"
                  element={<StaffApplicationsPage />}
                />
              </Route>
              <Route
                path="*"
                element={
                  <section className="panel state-panel">
                    <h1>Страница не найдена</h1>
                    <a className="button secondary" href="/">
                      На главную
                    </a>
                  </section>
                }
              />
            </Route>
          </Route>
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  );
}
