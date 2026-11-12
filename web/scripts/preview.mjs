// Same Node API as Vercel, bound to loopback for local development.
import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, sep, extname } from "node:path";
import handler from "../api/[route].js";

const root = fileURLToPath(new URL("../public/", import.meta.url));
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};
const port = Number(process.env.PORT || 3000);
http
  .createServer(async (req, res) => {
    const abort = new AbortController();
    res.on("close", () => abort.abort());
    try {
      const url = new URL(req.url, `http://${req.headers.host}`);
      if (url.pathname.startsWith("/api/")) {
        let size = 0;
        const chunks = [];
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 32768) {
            res.writeHead(413);
            res.end();
            return;
          }
          chunks.push(chunk);
        }
        const response = await handler.fetch(
          new Request(url, {
            method: req.method,
            headers: req.headers,
            signal: abort.signal,
            ...(["GET", "HEAD"].includes(req.method)
              ? {}
              : { body: Buffer.concat(chunks) }),
          }),
        );
        res.writeHead(response.status, Object.fromEntries(response.headers));
        if (response.body)
          for await (const part of response.body) {
            if (res.destroyed) break;
            res.write(part);
          }
      } else {
        const path = resolve(
          root,
          "." +
            decodeURIComponent(
              url.pathname === "/" ? "/index.html" : url.pathname,
            ),
        );
        if (!path.startsWith(resolve(root) + sep)) {
          res.writeHead(403);
          res.end();
          return;
        }
        const body = await readFile(path);
        res.writeHead(200, {
          "Content-Type": types[extname(path)] || "application/octet-stream",
          "Cache-Control": "no-store",
        });
        res.write(body);
      }
      res.end();
    } catch {
      if (!res.headersSent) res.writeHead(500);
      res.end("Preview request failed");
    }
  })
  .listen(port, "127.0.0.1", () =>
    process.stdout.write(`Local: http://127.0.0.1:${port}\n`),
  );
