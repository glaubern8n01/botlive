function snapshot() {
  if (document.body.dataset.shopLiveSimulator !== "true") return;
  chrome.runtime.sendMessage({
    type: "simulator.snapshot",
    payload: {
      snapshotId: document.body.dataset.snapshotId || null,
      product: document.querySelector("[data-current-product]")?.getAttribute("data-current-product") || null,
      nextProduct: document.querySelector("[data-next-product]")?.getAttribute("data-next-product") || null,
      comments: Number(document.querySelector("[data-comment-count]")?.getAttribute("data-comment-count") || 0),
      alert: document.querySelector("[role=alert]")?.textContent?.trim() || null
    }
  });
}
snapshot();
new MutationObserver(snapshot).observe(document.body, {subtree:true, childList:true, attributes:true});
