// Routes: /login, and the Console pages behind a login guard. The guard only checks "is someone logged in";
// the supervisor role is checked by the API on every request (a non-supervisor sees "Supervisor only").
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth.jsx";
import Shell from "./components/Shell.jsx";
import { ApiErrorView, Loading } from "./components/States.jsx";
import Login from "./screens/Login.jsx";
import LiveTickets from "./screens/LiveTickets.jsx";
import TicketDetail from "./screens/TicketDetail.jsx";

function RequireLogin({ children }) {
  const { session, status, refresh } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Loading text="Checking your session…" />;
  if (status === "unavailable") {
    return <div className="login-wrap"><div className="login-card"><ApiErrorView error={{ code: "unavailable" }} onRetry={refresh} /></div></div>;
  }
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireLogin><Shell /></RequireLogin>}>
            <Route path="/tickets" element={<LiveTickets />} />
            <Route path="/tickets/:ticketId" element={<TicketDetail />} />
          </Route>
          <Route path="*" element={<Navigate to="/tickets" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
