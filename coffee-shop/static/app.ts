// TypeScript for Coffee Shop UI
interface MenuItem {
  id: number;
  name: string;
  price: number;
  inventory: number;
}
interface Order {
  id: number;
  customer_name: string;
  items: string;
  total: number;
  created_at: string;
}

async function fetchMenu(): Promise<MenuItem[]> {
  const res = await fetch('/api/menu');
  return await res.json();
}
async function fetchOrders(): Promise<Order[]> {
  const res = await fetch('/api/orders');
  return await res.json();
}
async function addMenuItem(name: string, price: number, inventory: number): Promise<MenuItem> {
  const res = await fetch('/api/menu', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, price, inventory})
  });
  return await res.json();
}
async function placeOrder(customer_name: string, items: number[]): Promise<any> {
  const res = await fetch('/api/orders', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({customer_name, items})
  });
  return await res.json();
}
// Add more UI logic and event handlers as needed
