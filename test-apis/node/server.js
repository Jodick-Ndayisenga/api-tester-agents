const http = require("node:http");
const { URL } = require("node:url");

const port = Number(process.env.PORT || 8002);
const host = process.env.HOST || "127.0.0.1";
const users = new Map([
  [1, { id: 1, name: "Ada Lovelace", email: "ada@example.com" }],
  [2, { id: 2, name: "Grace Hopper", email: "grace@example.com" }],
]);

function send(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let raw = "";
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch (error) { reject(error); }
    });
    request.on("error", reject);
  });
}

function validUser(payload) {
  return payload && typeof payload.name === "string" && payload.name.length >= 2
    && typeof payload.email === "string" && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email);
}

async function handle(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const parts = url.pathname.split("/").filter(Boolean);
  const method = request.method;

  if (method === "GET" && url.pathname === "/health") return send(response, 200, { status: "ok", service: "node-fixture" });
  if (method === "GET" && url.pathname === "/api/v1/users") {
    const limit = Math.min(Number(url.searchParams.get("limit") || 20), 100);
    return send(response, 200, [...users.values()].slice(0, limit));
  }
  if (parts[0] !== "api" || parts[1] !== "v1") return send(response, 404, { error: "Not found" });

  if (method === "GET" && parts[2] === "users" && parts.length === 4) {
    const user = users.get(Number(parts[3]));
    return user ? send(response, 200, user) : send(response, 404, { error: "User not found" });
  }
  if (method === "POST" && url.pathname === "/api/v1/users") {
    let payload;
    try { payload = await readJson(request); } catch { return send(response, 400, { error: "Invalid JSON" }); }
    if (!validUser(payload)) return send(response, 422, { error: "name and email are required" });
    const id = Math.max(...users.keys()) + 1;
    const user = { id, name: payload.name, email: payload.email };
    users.set(id, user);
    return send(response, 201, user);
  }
  if ((method === "PUT" || method === "DELETE") && parts[2] === "users" && parts.length === 4) {
    const id = Number(parts[3]);
    if (!users.has(id)) return send(response, 404, { error: "User not found" });
    if (method === "DELETE") { users.delete(id); return send(response, 200, { deleted: true, id }); }
    let payload;
    try { payload = await readJson(request); } catch { return send(response, 400, { error: "Invalid JSON" }); }
    if (!validUser(payload)) return send(response, 422, { error: "name and email are required" });
    const user = { id, name: payload.name, email: payload.email };
    users.set(id, user);
    return send(response, 200, user);
  }
  if (method === "GET" && url.pathname === "/api/v1/search") {
    const q = url.searchParams.get("q");
    if (!q || q.length < 2) return send(response, 400, { error: "q is required" });
    return send(response, 200, { query: q, results: [...users.values()].filter((u) => u.name.toLowerCase().includes(q.toLowerCase())) });
  }
  if (method === "GET" && url.pathname === "/api/v1/admin/secret") {
    if (request.headers.authorization !== "Bearer test-token") return send(response, 401, { error: "Bearer token required" });
    return send(response, 200, { message: "admin access granted" });
  }
  if (method === "GET" && url.pathname === "/api/v1/buggy") return send(response, 500, { error: "Intentional fixture failure" });
  if (method === "GET" && url.pathname === "/api/v1/slow") {
    const delay = Math.min(Number(url.searchParams.get("delay_ms") || 100), 5000);
    await new Promise((resolve) => setTimeout(resolve, delay));
    return send(response, 200, { delay_ms: delay });
  }
  return send(response, 404, { error: "Not found" });
}

const server = http.createServer((request, response) => {
  handle(request, response).catch(() => send(response, 500, { error: "Unhandled fixture error" }));
});
server.listen(port, host, () => console.log(`Node fixture listening on http://${host}:${port}`));
