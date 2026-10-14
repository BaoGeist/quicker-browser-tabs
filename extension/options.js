const input = document.getElementById("label");

chrome.storage.local.get("label").then(({ label = "" }) => (input.value = label));
input.addEventListener("input", () => chrome.storage.local.set({ label: input.value.trim() }));
