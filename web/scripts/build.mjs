import { access, readFile } from "node:fs/promises";
const root = new URL("../", import.meta.url);
for (const path of [
  "public/index.html",
  "public/styles.css",
  "public/app.js",
  "public/citations.js",
  "public/brand/codehub.svg",
  "api/[route].js",
  "lib/cloud.js",
  "lib/search-config.json",
  "lib/chat-config.json",
]) {
  await access(new URL(path, root));
}
const html = await readFile(new URL("public/index.html", root), "utf8");
for (const path of ["/styles.css", "/app.js", "/brand/codehub.svg"]) {
  if (!html.includes(path))
    throw new Error("Missing local asset reference: " + path);
}
if (!html.includes('lang="el"'))
  throw new Error("Missing Greek language metadata");
console.log(
  "Static frontend ready in public/. Vercel hybrid RAG API ready in api/.",
);
