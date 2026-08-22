import { NavLink, Outlet } from 'react-router';
import { LayoutDashboard, Settings2, Users, History, Scissors, LogOut, ShoppingBag, BadgeDollarSign, Radio, FolderInput, Store, Scissors as Tesoura, Music2, UserCog, KeyRound, ListOrdered, BarChart3, Layers } from 'lucide-react';

export function Layout() {
  const handleLogout = () => {
    localStorage.removeItem('botlive_auth');
    window.location.reload();
  };

  const navItems = [
    { to: "/", icon: LayoutDashboard, label: "Painel" },
    { to: "/configuracao", icon: Settings2, label: "Configuração" },
    { to: "/canais", icon: Users, label: "Canais" },
    ...(import.meta.env.VITE_SHOP_LIVE_ENABLED === "true" ? [{ to: "/shop-live", icon: ShoppingBag, label: "Shop LIVE" }] : []),
    ...(import.meta.env.VITE_CAMPAIGNS_ENABLED === "true" ? [{ to: "/campanhas-cortes", icon: BadgeDollarSign, label: "Campanhas de Cortes" }] : []),
    ...(import.meta.env.VITE_MULTICHANNEL_ENABLED === "true" ? [{ to: "/canais-publicacao", icon: Radio, label: "Canais de publicação" }] : []),
    ...(import.meta.env.VITE_IMPORT_ENABLED === "true" ? [{ to: "/importar-adaptar", icon: FolderInput, label: "Importar / Adaptar" }] : []),
    ...(import.meta.env.VITE_COMMERCE_ENABLED === "true" ? [{ to: "/commerce-studio", icon: Store, label: "Commerce Studio" }] : []),
    ...(import.meta.env.VITE_MASS_ENABLED === "true" ? [{ to: "/producao-em-massa", icon: Layers, label: "Produção em Massa" }] : []),
    { to: "/kwai-cut", icon: Tesoura, label: "Kwai CUT" },
    { to: "/tiktok", icon: Music2, label: "TikTok" },
    { to: "/perfis", icon: UserCog, label: "Perfis" },
    { to: "/contas", icon: KeyRound, label: "Contas" },
    { to: "/fila", icon: ListOrdered, label: "Fila" },
    { to: "/metricas", icon: BarChart3, label: "Métricas" },
    { to: "/historico", icon: History, label: "Histórico" },
    { to: "/cortes", icon: Scissors, label: "Índice de Cortes" },
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 flex">
      <aside className="w-64 border-r border-zinc-800 bg-zinc-900/50 hidden md:flex flex-col">
        <div className="h-14 flex items-center px-6 border-b border-zinc-800">
          <h1 className="font-bold text-lg tracking-tight text-zinc-100">BotLive — Vigia</h1>
        </div>
        <nav className="flex-1 py-4 flex flex-col gap-1 px-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-zinc-800 text-zinc-50"
                    : "text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800/50"
                }`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-zinc-800">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 w-full rounded-md text-sm font-medium text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800/50 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sair
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 md:hidden border-b border-zinc-800 bg-zinc-900/50 flex items-center px-4 justify-between">
          <h1 className="font-bold text-lg tracking-tight text-zinc-100">BotLive</h1>
          <nav className="flex gap-3">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `p-2 rounded-md ${isActive ? "bg-zinc-800 text-zinc-50" : "text-zinc-400"}`
                }
              >
                <item.icon className="w-4 h-4" />
              </NavLink>
            ))}
          </nav>
        </header>

        <div className="flex-1 overflow-auto p-4 md:p-8">
          <div className="max-w-6xl mx-auto">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
}
