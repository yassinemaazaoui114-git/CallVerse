// "Ask about this order" (ShopNova customer): opens the Help chat with this order as the context (step 3).
// The chat adds " (order N)" to a message that names no order, exactly as the Streamlit page does (F1).
import { Navigate, useParams } from "react-router-dom";

export default function AskAboutOrder() {
  const { orderId } = useParams();
  return <Navigate to={`/shop/chat?order=${encodeURIComponent(orderId)}`} replace />;
}
