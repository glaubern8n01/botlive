import { useState } from 'react';
import { NavLink, Outlet } from 'react-router';
import { LayoutDashboard, Settings2, Users, History, Scissors, LogOut, ShoppingBag, BadgeDollarSign, Radio, FolderInput, Store, Scissors as Tesoura, Music2, UserCog, KeyRound, ListOrdered, BarChart3, Layers, Menu, X } from 'lucide-react';

export function Layout() {
  const [menuAberto, setMenuAberto] = useState(false);

  const handleLogout = () => {
    localStorage.removeItem('botlive_auth');
    window.location.reload();
  };

  const navItems = [
    { to: "/", icon: LayoutDashboard, label: "Painel" },
    { to: "/configuracao", icon: Settings2, label: "Configuração" },
    // "Canais" aqui sao os canais da Twitch que o vigia observa. Com a aba de
    // publicacao ligada, duas coisas diferentes competiam pela mesma palavra -
    // e a confusao ja custou tempo. O rotulo diz de qual dos dois se trata.
    { to: "/canais", icon: Users, label: "Canais vigiados" },
    ...(import.meta.env.VITE_SHOP_LIVE_ENABLED === "true" ? [{ to: "/shop-live", icon: ShoppingBag, label: "Shop LIVE" }] : []),
    ...(import.meta.env.VITE_CAMPAIGNS_ENABLED === "true" ? [{ to: "/campanhas-cortes", icon: BadgeDollarSign, label: "Campanhas de Cortes" }] : []),
    ...(import.meta.env.VITE_MULTICHANNEL_ENABLED === "true" ? [{ to: "/canais-publicacao", icon: Radio, label: "Publicação" }] : []),
    ...(import.meta.env.VITE_IMPORT_ENABLED === "true" ? [{ to: "/importar-adaptar", icon: FolderInput, label: "Importar / Adaptar" }] : []),
    ...(import.meta.env.VITE_COMMERCE_ENABLED === "true" ? [{ to: "/commerce-studio", icon: Store, label: "Commerce Studio" }] : []),
    // Shopee tem aba própria, como o documento pede: mesma infraestrutura,
    // dados e regras separados por plataforma.
    ...(import.meta.env.VITE_COMMERCE_ENABLED === "true" ? [{ to: "/shopee", icon: ShoppingBag, label: "Shopee" }] : []),
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
        {/* No celular a navegacao era uma fila de ate 18 icones sem rotulo, sem
            quebra e sem rolagem: tudo que passava da largura da tela ficava
            inalcancavel — Kwai CUT (10o da lista) simplesmente nao abria. Agora
            e um menu que rola, com o nome de cada aba. */}
        <header className="md:hidden border-b border-zinc-800 bg-zinc-900/50 relative">
          <div className="h-14 flex items-center px-4 justify-between">
            <h1 className="font-bold text-lg tracking-tight text-zinc-100">BotLive</h1>
            <button
              type="button"
              onClick={() => setMenuAberto((aberto) => !aberto)}
              aria-label={menuAberto ? "Fechar menu" : "Abrir menu"}
              aria-expanded={menuAberto}
              className="p-2 rounded-md text-zinc-300 hover:text-zinc-50 hover:bg-zinc-800/50 transition-colors"
            >
              {menuAberto ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>

          {menuAberto && (
            <nav className="absolute inset-x-0 top-14 z-50 max-h-[70vh] overflow-y-auto border-b border-zinc-800 bg-zinc-900 py-2 px-3 flex flex-col gap-1 shadow-lg">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setMenuAberto(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-3 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-zinc-800 text-zinc-50"
                        : "text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800/50"
                    }`
                  }
                >
                  <item.icon className="w-4 h-4 shrink-0" />
                  {item.label}
                </NavLink>
              ))}
              <button
                onClick={() => { setMenuAberto(false); handleLogout(); }}
                className="flex items-center gap-3 px-3 py-3 rounded-md text-sm font-medium text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800/50 transition-colors"
              >
                <LogOut className="w-4 h-4 shrink-0" />
                Sair
              </button>
            </nav>
          )}
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
