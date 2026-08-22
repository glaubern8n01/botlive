import React, { useState } from 'react';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/Card';

export function AuthWrapper({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return localStorage.getItem('botlive_auth') === 'true';
  });
  const [password, setPassword] = useState('');
  const [error, setError] = useState(false);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    // O app Windows injeta a senha em tempo de execução (window.__BOTLIVE_SENHA__),
    // porque lá a senha é o token sorteado na máquina do usuário — não existe em
    // tempo de build. No painel da VPS essa variável não existe e nada muda aqui.
    const senhaInjetada = (window as unknown as { __BOTLIVE_SENHA__?: string }).__BOTLIVE_SENHA__;
    const envPassword = senhaInjetada || import.meta.env.VITE_DASHBOARD_PASSWORD;

    // Fallback simple password just in case env var is missing or empty
    const checkPassword = envPassword || 'admin';
    
    if (password === checkPassword) {
      setIsAuthenticated(true);
      localStorage.setItem('botlive_auth', 'true');
      setError(false);
    } else {
      setError(true);
    }
  };

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Acesso Restrito</CardTitle>
          <CardDescription>
            Dashboard do BotLive. Insira a senha para continuar.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Input
                type="password"
                placeholder="Senha de acesso"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {error && <p className="text-sm text-red-500">Senha incorreta</p>}
            </div>
            <Button type="submit" className="w-full">
              Entrar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
