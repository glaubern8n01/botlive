let latestSnapshot = null;
chrome.runtime.onInstalled.addListener(() => chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}));
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "simulator.snapshot") {
    latestSnapshot = message.payload;
    chrome.runtime.sendMessage({type:"simulator.snapshot.forwarded",payload:latestSnapshot}).catch(() => {});
  }
  if (message.type === "simulator.snapshot.request") sendResponse(latestSnapshot);
  return true;
});
