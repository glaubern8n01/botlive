let socket = null;
let reconnects = 0;
let reconnectTimer = null;
let token = "";
const MAX_RECONNECTS = 5;
const $ = id => document.getElementById(id);

function setState(state) {
  $('status').textContent = state;
  for (const button of document.querySelectorAll('[data-command]')) button.hidden = button.dataset.state !== state;
  $('stop').hidden = !['executando','pausada'].includes(state);
}
function connect() {
  if (!token || socket?.readyState === WebSocket.OPEN) return;
  clearTimeout(reconnectTimer); setState('conectando');
  socket = new WebSocket(`ws://127.0.0.1:8765/shop-live/v1/events?token=${encodeURIComponent(token)}`);
  socket.onopen = () => { reconnects=0; setState('pronto'); $('panel').hidden=false; };
  socket.onclose = () => {
    setState('offline');
    if (token && reconnects < MAX_RECONNECTS) reconnectTimer=setTimeout(connect, Math.min(1000*2**reconnects++,8000));
  };
  socket.onmessage = message => {
    const event = JSON.parse(message.data);
    if (event.type === 'operation.context') renderContext(event.payload);
    if (['simulation.started','simulation.resumed'].includes(event.type)) setState('executando');
    if (event.type === 'simulation.paused') setState('pausada');
    if (['simulation.ready','simulation.stopped','simulation.completed'].includes(event.type)) setState('pronto');
    if (event.type === 'comment.received') $('comments').textContent=String(Number($('comments').textContent)+1);
    if (event.type === 'compliance.warning_received') { $('alerts').textContent=String(Number($('alerts').textContent)+1); $('alert').textContent=String(event.payload.problem); }
  };
}
function renderContext(context) {
  $('product').textContent=context.current_product?.name || 'Sem produto selecionado';
  $('next').textContent=`Próximo: ${context.next_product?.name || '—'}`;
  $('script').textContent=context.scripts?.map(block=>`${block.position}. ${block.text}`).join('\n') || 'Sem bloco de roteiro cadastrado.';
  $('materials').textContent=context.materials?.map(item=>`${item.position}. ${item.planned_duration_seconds}s`).join(' · ') || 'Sem materiais ordenados.';
}
function command(action) {
  if (socket?.readyState !== WebSocket.OPEN) return;
  const sessionId=$('session').value.trim();
  socket.send(JSON.stringify({action,speed:2,session_id:action==='start'&&sessionId?sessionId:null}));
}
$('auth').addEventListener('submit', event => { event.preventDefault(); token=$('token').value.trim(); if(!token)return; chrome.storage.session.set({shopLiveToken:token}); socket?.close(); connect(); });
for (const button of document.querySelectorAll('[data-command]')) button.addEventListener('click',()=>command(button.dataset.command));
$('stop').addEventListener('click',()=>command('stop'));
function renderSnapshot(snapshot){$('snapshot-id').textContent=snapshot.snapshotId||'snapshot ausente';$('comments').textContent=String(snapshot.comments||0);if(snapshot.alert)$('alert').textContent=snapshot.alert;}
chrome.runtime.onMessage.addListener(message => { if(message.type==='simulator.snapshot.forwarded') renderSnapshot(message.payload); });
chrome.runtime.sendMessage({type:'simulator.snapshot.request'}, snapshot => { if(snapshot) renderSnapshot(snapshot); });
chrome.storage.session.get('shopLiveToken').then(saved => { token=saved.shopLiveToken||''; if(token){$('token').value=token;connect();} });
