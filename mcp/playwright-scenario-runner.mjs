#!/usr/bin/env node
/**
 * Local bridge to Playwright MCP.
 *
 * This process receives only a base URL and scenario values. It deliberately
 * has no credential arguments: the consultant signs in in the visible Edge
 * profile before a scenario starts.
 */
import { spawn } from "node:child_process";
import readline from "node:readline";
import { dirname, join } from "node:path";

const [mode = "inspect", profileDir = "", webUrl = ""] = process.argv.slice(2);
const npxCli = join(dirname(process.execPath), "node_modules", "npm", "bin", "npx-cli.js");
const command = process.platform === "win32" ? process.execPath : "npx";
const commandArgs = process.platform === "win32" ? [npxCli] : [];
const server = spawn(command, [...commandArgs, "-y", "@playwright/mcp@0.0.80", "--browser", "msedge", ...(profileDir ? ["--user-data-dir", profileDir] : [])], { stdio: ["pipe", "pipe", "pipe"], env: process.env, windowsHide: true });
const pending = new Map();
let requestId = 0;
let serverError = "";
readline.createInterface({ input: server.stdout }).on("line", (line) => {
  try {
    const message = JSON.parse(line);
    const resolver = pending.get(message.id);
    if (resolver) {
      pending.delete(message.id);
      message.error ? resolver.reject(new Error(message.error.message || "MCP request failed")) : resolver.resolve(message.result);
    }
  } catch { /* Ignore non-protocol server diagnostics. */ }
});
server.stderr.on("data", (chunk) => { serverError += chunk.toString(); });
server.on("exit", (code) => {
  for (const { reject } of pending.values()) reject(new Error(serverError || `Playwright MCP stopped with code ${code}.`));
  pending.clear();
});
function request(method, params = {}) {
  const id = ++requestId;
  server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
function notify(method, params = {}) {
  server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
}
await request("initialize", {
  protocolVersion: "2025-03-26",
  capabilities: {},
  clientInfo: { name: "1c-consultant-scenario-runner", version: "1.0.0" },
});
notify("notifications/initialized");
try {
  if (mode === "inspect") {
    const result = await request("tools/list");
    process.stdout.write(JSON.stringify(result.tools, null, 2));
  } else if (mode === "session") {
    if (!webUrl) throw new Error("A web-client URL is required for login mode.");
    await request("tools/call", { name: "browser_navigate", arguments: { url: webUrl } });
    await request("tools/call", { name: "browser_wait_for", arguments: { time: 5 } });
    // This is deliberately the only interactive part. The password is typed by
    // the consultant in Edge, never passed through this process or an MCP call.
    process.stdout.write("READY_FOR_MANUAL_LOGIN\n");
    for await (const command of readline.createInterface({ input: process.stdin })) {
      if (command === "LOGIN_COMPLETE") {
        const page = await request("tools/call", { name: "browser_evaluate", arguments: { function: "() => document.body.innerText.slice(0, 2000)" } });
        const text = JSON.stringify(page);
        process.stdout.write(`${text.includes("Войти") ? "LOGIN_NOT_CONFIRMED" : "LOGIN_CONFIRMED"}\n`);
      }
      if (command.startsWith("CALL ")) {
        try {
          const payload = JSON.parse(command.slice(5));
          const result = await request("tools/call", { name: payload.name, arguments: payload.arguments ?? {} });
          process.stdout.write(`RESULT ${JSON.stringify({ ok: true, result })}\n`);
        } catch (error) {
          process.stdout.write(`RESULT ${JSON.stringify({ ok: false, error: error.message })}\n`);
        }
      }
      if (command === "STOP") break;
    }
  } else if (mode === "snapshot") {
    if (!webUrl) throw new Error("A web-client URL is required for snapshot mode.");
    await request("tools/call", { name: "browser_navigate", arguments: { url: webUrl } });
    await request("tools/call", { name: "browser_wait_for", arguments: { time: 8 } });
    const result = await request("tools/call", { name: "browser_snapshot", arguments: { depth: 2 } });
    process.stdout.write(JSON.stringify(result, null, 2));
  } else if (mode === "page-text") {
    if (!webUrl) throw new Error("A web-client URL is required for page-text mode.");
    await request("tools/call", { name: "browser_navigate", arguments: { url: webUrl } });
    await request("tools/call", { name: "browser_wait_for", arguments: { time: 8 } });
    const result = await request("tools/call", { name: "browser_evaluate", arguments: { function: "() => document.body.innerText.slice(0, 12000)" } });
    process.stdout.write(JSON.stringify(result, null, 2));
  } else {
    throw new Error(`Unknown runner mode: ${mode}`);
  }
} finally {
  server.kill();
}
