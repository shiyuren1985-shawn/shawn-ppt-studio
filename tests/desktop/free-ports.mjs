#!/usr/bin/env node

import net from "node:net";

function listen() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

const first = await listen();
const second = await listen();
const ports = [first.address().port, second.address().port];
await Promise.all([
  new Promise((resolve) => first.close(resolve)),
  new Promise((resolve) => second.close(resolve)),
]);
process.stdout.write(`${ports[0]} ${ports[1]}\n`);
