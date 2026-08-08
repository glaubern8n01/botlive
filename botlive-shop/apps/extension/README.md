# Extensão Chrome MV3

Carregue esta pasta em `chrome://extensions` → modo do desenvolvedor → **Carregar sem compactação**. Ela só possui acesso ao agente local e à página `/shop-live/simulator-page`; não declara acesso ao TikTok.

O token fica em `chrome.storage.session`. O content script apenas lê atributos da página simulada. Integração real permanece `UNVERIFIED` e desabilitada.
