import { BrowserRouter, Routes, Route } from "react-router";
import { AuthWrapper } from "./components/AuthWrapper";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { Configuracao } from "./pages/Configuracao";
import { Canais } from "./pages/Canais";
import { Historico } from "./pages/Historico";
import { Cortes } from "./pages/Cortes";
import { ShopLive } from "./pages/ShopLive";

export default function App() {
  return (
    <BrowserRouter>
      <AuthWrapper>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="configuracao" element={<Configuracao />} />
            <Route path="canais" element={<Canais />} />
            <Route path="historico" element={<Historico />} />
            <Route path="cortes" element={<Cortes />} />
            {import.meta.env.VITE_SHOP_LIVE_ENABLED === "true" && <Route path="shop-live" element={<ShopLive />} />}
          </Route>
        </Routes>
      </AuthWrapper>
    </BrowserRouter>
  );
}
