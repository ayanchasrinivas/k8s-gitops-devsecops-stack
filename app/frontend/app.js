const API_BASE = "/api";

const listEl = document.getElementById("item-list");
const emptyEl = document.getElementById("empty-state");
const formEl = document.getElementById("item-form");
const nameEl = document.getElementById("item-name");
const descEl = document.getElementById("item-desc");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const podNameEl = document.getElementById("pod-name");
const refreshBtn = document.getElementById("refresh-btn");

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/info`);
    if (!res.ok) throw new Error("bad response");
    const data = await res.json();
    statusDot.className = "status-dot ok";
    statusText.textContent = "backend connected";
    podNameEl.textContent = data.hostname;
  } catch (e) {
    statusDot.className = "status-dot err";
    statusText.textContent = "backend unreachable";
    podNameEl.textContent = "n/a";
  }
}

async function loadItems() {
  try {
    const res = await fetch(`${API_BASE}/items`);
    const items = await res.json();
    listEl.innerHTML = "";
    emptyEl.style.display = items.length === 0 ? "block" : "none";
    for (const item of items) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="item-info">
          <strong></strong>
          <span></span>
        </div>
        <button class="delete-btn">remove</button>
      `;
      li.querySelector("strong").textContent = item.name;
      li.querySelector("span").textContent = item.description || "";
      li.querySelector(".delete-btn").addEventListener("click", () => deleteItem(item.id));
      listEl.appendChild(li);
    }
  } catch (e) {
    emptyEl.style.display = "block";
    emptyEl.textContent = "Could not load tasks — backend may be down.";
  }
}

async function deleteItem(id) {
  await fetch(`${API_BASE}/items/${id}`, { method: "DELETE" });
  loadItems();
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  await fetch(`${API_BASE}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: nameEl.value, description: descEl.value }),
  });
  nameEl.value = "";
  descEl.value = "";
  loadItems();
});

refreshBtn.addEventListener("click", loadItems);

checkHealth();
loadItems();
setInterval(checkHealth, 10000);
