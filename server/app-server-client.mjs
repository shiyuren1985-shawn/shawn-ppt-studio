import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import readline from "node:readline";

const DEFAULT_CODEX_APP = "/Applications/ChatGPT.app/Contents/Resources/codex";

export function resolveCodexExecutable(env = process.env) {
  if (env.CODEX_BIN) return env.CODEX_BIN;
  if (env.PPT_AI_LAB_CODEX_BIN) return env.PPT_AI_LAB_CODEX_BIN;
  if (existsSync(DEFAULT_CODEX_APP)) return DEFAULT_CODEX_APP;
  return "codex";
}

export class AppServerClient extends EventEmitter {
  constructor({ executable, cwd, env = process.env, requestTimeoutMs = 30_000 }) {
    super();
    this.executable = executable;
    this.cwd = cwd;
    this.env = env;
    this.requestTimeoutMs = requestTimeoutMs;
    this.child = null;
    this.nextId = 1;
    this.pending = new Map();
    this.serverRequests = new Map();
    this.ready = false;
    this.account = null;
    this.lastError = null;
    this.stderrTail = "";
    this.stopping = false;
    this.startPromise = null;
  }

  get pid() {
    return this.child?.pid || null;
  }

  start() {
    if (this.startPromise) return this.startPromise;
    if (this.ready) return Promise.resolve();
    this.startPromise = this.#start().finally(() => { this.startPromise = null; });
    return this.startPromise;
  }

  async #start() {
    this.stopping = false;
    this.stderrTail = "";

    const child = spawn(this.executable, ["app-server", "--stdio"], {
      cwd: this.cwd,
      env: this.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      this.stderrTail = `${this.stderrTail}${chunk}`.slice(-8192);
    });

    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      if (this.child === child) this.#handleLine(line);
    });
    child.stdin.on("error", (error) => this.#handleExit(error, child));

    child.once("error", (error) => this.#handleExit(error, child));
    child.once("exit", (code, signal) => {
      const message = this.stopping
        ? "Codex App Server stopped"
        : `Codex App Server exited (code=${code ?? "null"}, signal=${signal ?? "null"})`;
      this.#handleExit(Object.assign(new Error(message), { code: "app_server_exited" }), child);
    });

    await new Promise((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", reject);
    });

    try {
      await this.request("initialize", {
        clientInfo: {
          name: "shawn_ppt_studio",
          title: "Shawn PPT Studio",
          version: "0.1.0",
        },
        capabilities: {
          experimentalApi: true,
        },
      });
      this.notify("initialized", {});
      const accountResult = await this.request("account/read", { refreshToken: false });
      this.account =
        accountResult && Object.hasOwn(accountResult, "account")
          ? accountResult.account
          : accountResult ?? null;
      this.ready = true;
      this.lastError = null;
    } catch (error) {
      this.lastError = error;
      await this.stop();
      throw error;
    }
  }

  request(method, params = {}, timeoutMs = this.requestTimeoutMs) {
    if (!this.child?.stdin?.writable) {
      return Promise.reject(Object.assign(new Error("Codex App Server is not running"), { code: "app_server_unavailable" }));
    }

    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(Object.assign(new Error(`Codex App Server request timed out: ${method}`), { code: "app_server_timeout" }));
      }, timeoutMs);
      timer.unref?.();

      this.pending.set(id, { resolve, reject, timer, method });
      this.#write({ method, id, params });
    });
  }

  notify(method, params = {}) {
    this.#write({ method, params });
  }

  subscribe(listener) {
    this.on("notification", listener);
    return () => this.off("notification", listener);
  }

  subscribeServerRequests(listener) {
    this.on("serverRequest", listener);
    return () => this.off("serverRequest", listener);
  }

  serverRequest(requestId) {
    return this.serverRequests.get(String(requestId)) || null;
  }

  respondToServerRequest(requestId, result) {
    const key = String(requestId);
    const request = this.serverRequests.get(key);
    if (!request) {
      throw Object.assign(new Error("Codex permission request is no longer active"), {
        code: "approval_request_not_found",
      });
    }
    this.#write({ id: request.id, result });
    this.serverRequests.delete(key);
  }

  rejectServerRequest(requestId, error) {
    const key = String(requestId);
    const request = this.serverRequests.get(key);
    if (!request) {
      throw Object.assign(new Error("Codex permission request is no longer active"), {
        code: "approval_request_not_found",
      });
    }
    this.#write({ id: request.id, error });
    this.serverRequests.delete(key);
  }

  async stop() {
    const child = this.child;
    if (!child) return;
    this.stopping = true;
    this.ready = false;

    const exited = new Promise((resolve) => child.once("exit", resolve));
    child.kill("SIGTERM");
    const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
    timer.unref?.();
    let deadline;
    await Promise.race([exited, new Promise((resolve) => { deadline = setTimeout(resolve, 3500); })]);
    clearTimeout(timer);
    clearTimeout(deadline);
    if (this.child === child) this.#handleExit(Object.assign(new Error("Codex App Server stopped"), { code: "app_server_exited" }), child);
  }

  #write(message) {
    try {
      this.child.stdin.write(`${JSON.stringify(message)}\n`);
    } catch (error) {
      this.#handleExit(error);
      throw error;
    }
  }

  #handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.emit("protocolError", new Error("Codex App Server emitted invalid JSONL"));
      return;
    }

    if (!message || typeof message !== "object" || Array.isArray(message)) {
      this.emit("protocolError", new Error("Codex App Server emitted an invalid message"));
      return;
    }

    if (Object.hasOwn(message, "id") && !message.method) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) {
        const error = Object.assign(
          new Error(message.error.message || `Codex App Server request failed: ${pending.method}`),
          { code: message.error.code || "app_server_request_failed", data: message.error.data },
        );
        pending.reject(error);
      } else {
        pending.resolve(message.result);
      }
      return;
    }

    if (message.method && Object.hasOwn(message, "id")) {
      const key = String(message.id);
      this.serverRequests.set(key, message);
      this.emit("serverRequest", { ...message, requestId: key });
      return;
    }

    if (message.method) {
      if (message.method === "serverRequest/resolved") {
        this.#resolveServerRequests((request) => (
          String(request.id) === String(message.params?.requestId)
          && request.params?.threadId === message.params?.threadId
        ), "server_resolved");
      } else if (message.method === "turn/completed") {
        this.#resolveServerRequests((request) => (
          request.params?.threadId === message.params?.threadId
          && request.params?.turnId === message.params?.turn?.id
        ), "turn_completed");
      }
      this.emit("notification", message);
    }
  }

  #resolveServerRequests(matches, reason) {
    for (const [key, request] of this.serverRequests) {
      if (!matches(request)) continue;
      this.serverRequests.delete(key);
      this.emit("serverRequestResolved", { request: { ...request, requestId: key }, reason });
    }
  }

  #handleExit(error, child = this.child) {
    if (!child || this.child !== child) return;
    this.child = null;
    this.ready = false;
    this.account = null;
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    this.lastError = error;
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(error);
    }
    this.pending.clear();
    this.#resolveServerRequests(() => true, "connection_closed");
    this.emit("appServerError", error);
  }
}
