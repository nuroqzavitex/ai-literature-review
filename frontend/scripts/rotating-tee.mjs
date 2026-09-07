#!/usr/bin/env node
/** Copy process input to Docker stdout and a capped log file without archives. */
import fs from "node:fs";
import path from "node:path";

const target = process.argv[2];
const maxBytes = Number(process.argv[3] ?? 500 * 1024 * 1024);

if (!target || !Number.isInteger(maxBytes) || maxBytes < 1) {
  throw new Error("Usage: rotating-tee.mjs <path> [max-bytes]");
}

fs.mkdirSync(path.dirname(target), { recursive: true });
function rotate() {
  fs.rmSync(target, { force: true });
}

if (fs.existsSync(target) && fs.statSync(target).size >= maxBytes) rotate();
let size = fs.existsSync(target) ? fs.statSync(target).size : 0;
let descriptor = fs.openSync(target, "a");

process.stdin.on("data", (chunk) => {
  process.stdout.write(chunk);
  let offset = 0;
  while (offset < chunk.length) {
    if (size >= maxBytes) {
      fs.closeSync(descriptor);
      rotate();
      descriptor = fs.openSync(target, "a");
      size = 0;
    }
    const writable = Math.min(maxBytes - size, chunk.length - offset);
    fs.writeSync(descriptor, chunk.subarray(offset, offset + writable));
    offset += writable;
    size += writable;
  }
});

process.stdin.on("end", () => fs.closeSync(descriptor));
