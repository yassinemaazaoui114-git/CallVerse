// Routes: /login, the Console pages (supervisor) and the ShopNova customer pages behind a login guard, and
// /workspace for the accounts whose pages are not built yet. The guard only checks "is someone logged in";
// the ROLE is checked by the API on every request (a wrong role sees "Not available for your account").
// After login an account goes to its own home (hooks.homeFor): supervisor → Console, ShopNova customer →
// My orders, everyone else → /workspace.
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth.jsx";
import Shell from "./components/Shell.jsx";
import { ApiErrorView, Loading } from "./components/States.jsx";
import { homeFor } from "./hooks.js";
import AskAboutOrder from "./screens/AskAboutOrder.jsx";
import AdminApprovals from "./screens/AdminApprovals.jsx";
import Chat from "./screens/Chat.jsx";
import LiveTickets from "./screens/LiveTickets.jsx";
import Login from "./screens/Login.jsx";
import MyOrders from "./screens/MyOrders.jsx";
import OrderDetail from "./screens/OrderDetail.jsx";
import TicketDetail from "./screens/TicketDetail.jsx";
import Workspace from "./screens/Workspace.jsx";

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

function Home() {
  const { session } = useAuth();
  return <Navigate to={homeFor(session)} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireLogin><Shell area="console" /></RequireLogin>}>
            <Route path="/tickets" element={<LiveTickets />} />
            <Route path="/tickets/:ticketId" element={<TicketDetail />} />
          </Route>
          <Route element={<RequireLogin><Shell area="shopnova" /></RequireLogin>}>
            <Route path="/shop/orders" element={<MyOrders />} />
            <Route path="/shop/orders/:orderId" element={<OrderDetail />} />
            <Route path="/shop/orders/:orderId/ask" element={<AskAboutOrder />} />
            <Route path="/shop/chat" element={<Chat />} />
          </Route>
          <Route element={<RequireLogin><Shell area="shopnova-admin" /></RequireLogin>}>
            <Route path="/admin/approvals" element={<AdminApprovals />} />
          </Route>
          <Route element={<RequireLogin><Shell area="none" /></RequireLogin>}>
            <Route path="/workspace" element={<Workspace />} />
          </Route>
          <Route path="*" element={<RequireLogin><Home /></RequireLogin>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
