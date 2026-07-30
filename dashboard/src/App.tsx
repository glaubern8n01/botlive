import { BrowserRouter, Routes, Route } from "react-router";
import { AuthWrapper } from "./components/AuthWrapper";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { Configuracao } from "./pages/Configuracao";
import { Canais } from "./pages/Canais";
import { Historico } from "./pages/Historico";
import { Cortes } from "./pages/Cortes";
import { Perfis } from "./pages/Perfis";
import { Fila } from "./pages/Fila";
import { Contas } from "./pages/Contas";
import { Metricas } from "./pages/Metricas";
import { KwaiCut } from "./pages/KwaiCut";

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
            <Route path="perfis" element={<Perfis />} />
            <Route path="fila" element={<Fila />} />
            <Route path="contas" element={<Contas />} />
            <Route path="metricas" element={<Metricas />} />
            <Route path="kwai-cut" element={<KwaiCut />} />
          </Route>
        </Routes>
      </AuthWrapper>
    </BrowserRouter>
  );
}
