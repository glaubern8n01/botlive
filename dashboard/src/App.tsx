import { BrowserRouter, Routes, Route } from "react-router";
import { AuthWrapper } from "./components/AuthWrapper";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { Configuracao } from "./pages/Configuracao";
import { Canais } from "./pages/Canais";
import { Historico } from "./pages/Historico";
import { Cortes } from "./pages/Cortes";
import { ShopLive } from "./pages/ShopLive";
import { CampanhasCortes } from "./pages/CampanhasCortes";
export default function App(){return <BrowserRouter><AuthWrapper><Routes><Route path="/" element={<Layout/>}><Route index element={<Home/>}/><Route path="configuracao" element={<Configuracao/>}/><Route path="canais" element={<Canais/>}/><Route path="historico" element={<Historico/>}/><Route path="cortes" element={<Cortes/>}/>{import.meta.env.VITE_SHOP_LIVE_ENABLED==="true"&&<Route path="shop-live" element={<ShopLive/>}/>} {import.meta.env.VITE_CAMPAIGNS_ENABLED==="true"&&<Route path="campanhas-cortes" element={<CampanhasCortes/>}/>}</Route></Routes></AuthWrapper></BrowserRouter>}
