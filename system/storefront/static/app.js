/* Lotus's demo storefront — cart + checkout against the checkout service via /api/*. */
const META = [
  [/rice|jasmine/i, "🍚", "#fdf3d8", "Pantry"],
  [/egg/i, "🥚", "#f8ecd9", "Fresh"],
  [/milk/i, "🥛", "#e8f1fb", "Fresh"],
  [/noodle|ramen/i, "🍜", "#fae8dd", "Pantry"],
  [/coffee/i, "☕", "#efe6dd", "Pantry"],
  [/banana|fruit/i, "🍌", "#fdf6d4", "Fresh"],
  [/chicken/i, "🍗", "#f6e8e0", "Fresh"],
  [/shrimp|fish|seafood/i, "🦐", "#e0f0f2", "Fresh"],
  [/vegetable|broccoli|greens|veg/i, "🥬", "#e2f3e4", "Fresh"],
  [/snack|chip/i, "🍿", "#f6ecd9", "Pantry"],
  [/detergent|clean/i, "🧴", "#e4ecf8", "Household"],
  [/shampoo|soap/i, "🧼", "#e8f0f7", "Household"],
];
const metaFor = (name) => META.find(([re]) => re.test(name)) || [null, "🛍️", "#eef0f3", "Grocery"];
const thb = (c) => "฿" + (c / 100).toFixed(2);
const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// one id per checkout attempt: it rides as X-Request-ID end to end and doubles as the
// payments idempotency key, so retrying a timed-out order replays instead of recharging
const newReqId = () => "req_" + Array.from(crypto.getRandomValues(new Uint8Array(6)),
  (b) => b.toString(16).padStart(2, "0")).join("");
let checkoutRid = null;

let products = [], cart = {};   // id -> qty

async function load() {
  const rid = document.getElementById("rid");
  rid.textContent = document.querySelector("meta[name=x-req]")?.content || "(see response header)";
  try { products = await (await fetch("/api/products")).json(); }
  catch { document.getElementById("grid").innerHTML = "<p class='loading'>Store unavailable — upstream down.</p>"; return; }
  document.getElementById("grid").innerHTML = products.map(p => {
    const [, emoji, bg, cat] = metaFor(p.name);
    return `<div class="card"><div class="tile" style="background:${bg}">${emoji}</div>
      <div class="body"><span class="cat">${cat}</span><span class="name">${esc(p.name)}</span>
      <span class="price">${thb(p.price_cents)}</span>
      <button class="add" onclick="add(${+p.id})">Add to cart</button></div></div>`;
  }).join("");
}

function add(id) { cart[id] = (cart[id] || 0) + 1; render(); openDrawer(); }
function chg(id, d) { cart[id] = Math.max(0, (cart[id] || 0) + d); if (!cart[id]) delete cart[id]; render(); }
function subtotal() {
  return Object.entries(cart).reduce((s, [id, q]) => {
    const p = products.find(x => x.id == id); return s + (p ? p.price_cents * q : 0);
  }, 0);
}
function render() {
  const n = Object.values(cart).reduce((a, b) => a + b, 0);
  document.getElementById("cartCount").textContent = n;
  const box = document.getElementById("cartItems");
  if (!n) { box.innerHTML = "<p class='cart-empty'>Cart is empty</p>"; }
  else box.innerHTML = Object.entries(cart).map(([id, q]) => {
    const p = products.find(x => x.id == id); if (!p) return "";
    const [, emoji] = metaFor(p.name);
    return `<div class="ci"><span class="emoji">${emoji}</span><div class="grow">
      <div class="n">${esc(p.name)}</div><div class="p">${thb(p.price_cents)} × ${q}</div></div>
      <div class="qty"><button onclick="chg(${id},-1)">−</button><b>${q}</b>
      <button onclick="chg(${id},1)">+</button></div></div>`;
  }).join("");
  document.getElementById("subtotal").textContent = thb(subtotal());
}

const $ = (id) => document.getElementById(id);
function openDrawer() { $("drawer").hidden = $("scrim").hidden = false; }
function closeAll() { ["drawer","scrim","modal","confirm"].forEach(i => $(i).hidden = true); }

$("cartBtn").onclick = openDrawer;
$("scrim").onclick = closeAll;
$("closeDrawer").onclick = closeAll;
$("closeModal").onclick = closeAll;
$("confirmDone").onclick = closeAll;
$("checkoutBtn").onclick = async () => {
  if (!subtotal()) return;
  checkoutRid = newReqId();   // fresh id per checkout attempt; retries below reuse it
  const items = Object.entries(cart).map(([id, q]) => ({ product_id: +id, quantity: q }));
  $("modal").hidden = false;
  $("quoteRows").innerHTML = "<p class='loading'>Fetching quote…</p>";
  try {
    const r = await fetch("/api/quote", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
    });
    const q = await r.json();
    if (!r.ok || typeof q.total_cents !== "number") throw new Error(q.reason || r.status);
    $("quoteRows").innerHTML =
      `<div class="row"><span>Items</span><span>${thb(q.subtotal_cents)}</span></div>` +
      (q.discount_cents ? `<div class="row"><span>Discount</span><span>−${thb(q.discount_cents)}</span></div>` : "") +
      `<div class="row"><span>Tax</span><span>${thb(q.tax_cents)}</span></div>` +
      `<div class="row"><span>Delivery</span><span>${q.shipping_cents ? thb(q.shipping_cents) : "Free"}</span></div>`;
    $("modalTotal").textContent = thb(q.total_cents);
  } catch {
    $("quoteRows").innerHTML = `<div class="row"><span>Subtotal</span><span>${thb(subtotal())}</span></div>` +
      `<div class="row muted"><span>Total</span><span>set at checkout</span></div>`;
    $("modalTotal").textContent = "—";
  }
};

$("checkoutForm").onsubmit = async (e) => {
  e.preventDefault();
  $("payBtn").disabled = true; $("payErr").hidden = true;
  const items = Object.entries(cart).map(([id, q]) => ({ product_id: +id, quantity: q }));
  let resp, rid = checkoutRid || newReqId();
  try {
    resp = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Request-ID": rid },
      body: JSON.stringify({ items }),
    });
    rid = resp.headers.get("x-request-id") || "";
    const body = await resp.json();
    $("modal").hidden = true;
    const ok = resp.ok && body.status === "succeeded";
    $("confirmIcon").textContent = ok ? "✅" : "❌";
    $("confirmTitle").textContent = ok ? `Order #${body.order_id} placed` : "Payment declined";
    $("confirmDetail").textContent = ok
      ? `${thb(body.authorized_amount_cents)} charged — see you at the door.`
      : `${body.decline_reason || body.status || "error"} — nothing was charged.`;
    $("confirmRid").textContent = rid || "—";
    $("confirmRid2").textContent = rid || "";
    $("confirm").hidden = false;
    if (ok) { cart = {}; render(); }
  } catch (err) {
    // payment state unknown on a timeout - do NOT claim "nothing was charged". A retry is
    // safe because we resend the same X-Request-ID, which is the PSP idempotency key.
    $("payErr").textContent = `Connection lost (${err}) — retry is safe: request id ${rid} replays instead of double-charging.`;
    $("payErr").hidden = false;
  }
  $("payBtn").disabled = false;
};

load();
