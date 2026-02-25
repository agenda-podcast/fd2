/* Minimal static server for FD pipeline branch (no build tooling). */
const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = 8080;
const ROOT = path.join(__dirname, "public");

function readFileSafe(p) {
  try {
    return fs.readFileSync(p);
  } catch (e) {
    return null;
  }
}

function contentType(p) {
  const ext = path.extname(p).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".json") return "application/json; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer((req, res) => {
  const url = req.url || "/";
  const clean = url.split("?")[0];
  const rel = clean === "/" ? "/index.html" : clean;
  const target = path.join(ROOT, rel);
  if (!target.startsWith(ROOT)) {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Bad request");
    return;
  }
  const data = readFileSafe(target);
  if (data === null) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
    return;
  }
  res.writeHead(200, { "Content-Type": contentType(target) });
  res.end(data);
});

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write("FD pipeline server listening on http://127.0.0.1:" + PORT + "\n");
});
