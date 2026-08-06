@echo off
REM Relay do Kwai CUT no PC: baixa fontes de futebol (IP residencial), sobe pra
REM VPS e dispara o corte. Roda em loop ate encher o estoque (--target) e fica
REM aguardando. Auto-inicia no logon (tarefa agendada "BotLive-Relay").
REM Para parar: feche esta janela. Prioridade do PC quando ligado; quando o PC
REM esta desligado, o mesmo relay no celular (Termux) mantem o estoque.
title BotLive Relay (Kwai CUT)
set PYTHONUTF8=1
set RELAY_WORK=G:\botlive-relay-tmp
set VPS_OUTPUT_VOLUME=/var/lib/docker/volumes/botlive_botlive-app_botlive-output/_data
set RELAY_MAX_HEIGHT=720
cd /d G:\botlive
:loop
python relay_run.py --loop --target 100
echo.
echo [relay] processo saiu; reiniciando em 60s (feche a janela para parar)...
timeout /t 60 /nobreak >nul
goto loop
