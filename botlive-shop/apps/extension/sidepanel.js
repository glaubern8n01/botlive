let socket;
const $ = id => document.getElementById(id);
$('auth').addEventListener('submit', event => {
  event.preventDefault();
  const token = $('token').value.trim();
  if (!token) return;
  chrome.storage.session.set({shopLiveToken: token});
  socket?.close();
  socket = new WebSocket(`ws://127.0.0.1:8765/shop-live/v1/events?token=${encodeURIComponent(token)}`);
  socket.onopen = () => $('status').textContent = 'Agente conectado';
  socket.onclose = () => $('status').textContent = 'Desconectado';
  socket.onmessage = message => {
    const eventData = JSON.parse(message.data);
    $('panel').hidden = false;
    if (eventData.type === 'comment.received') $('comments').textContent = String(Number($('comments').textContent) + 1);
    if (eventData.type === 'compliance.warning_received') { $('alerts').textContent = String(Number($('alerts').textContent) + 1); $('alert').textContent = eventData.payload.problem; }
  };
});
chrome.runtime.onMessage.addListener(message => {
  if (message.type !== 'simulator.snapshot') return;
  $('panel').hidden = false;
  $('product').textContent = message.payload.product || 'Produto não identificado';
  $('next').textContent = `Próximo: ${message.payload.nextProduct || '—'}`;
  $('comments').textContent = String(message.payload.comments || 0);
  if (message.payload.alert) $('alert').textContent = message.payload.alert;
});
