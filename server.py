"""
Les Faits — Serveur local minimal
================================
Usage :
    python server.py              # port 8080 par défaut
    python server.py --port 3000

Endpoints :
    GET  /                 → index.html
    GET  /api/articles     → liste articles (data/articles.json)
    POST /api/generate     → génère un article  { "sujet": "...", "nb_sources": 5 }
    GET  /api/status       → statut du serveur
"""

import os, json, sys, argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from io import BytesIO

ROOT = Path(__file__).parent


class FactuelHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {self.path} → {args[1] if len(args)>1 else ''}")

    # ── Routeur ──────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "" or path == "/":
            self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")
        elif path == "/api/articles":
            self._api_articles()
        elif path == "/api/status":
            self._json({"status": "ok", "version": "1.0", "protocole": "v1.1"})
        else:
            super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/generate":
            self._api_generate()
        else:
            self._json({"error": "Route non trouvée"}, status=404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ── Handlers API ─────────────────────────────────────────────────────────

    def _api_articles(self):
        index_path = ROOT / "data" / "articles.json"
        if not index_path.exists():
            return self._json([])
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self._json(data)

    def _api_generate(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._json({"error": "Corps JSON invalide"}, status=400)

        sujet = body.get("sujet", "").strip()
        if not sujet:
            return self._json({"error": "Champ 'sujet' requis"}, status=400)

        nb_sources = int(body.get("nb_sources", 5))

        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from generate_article import generate, save
            art = generate(sujet, nb_sources)
            save(art)
            self._json({"ok": True, "slug": art["slug"], "titre": art["titre"],
                        "nb_sources": art["nb_sources"], "confiance": art["confiance"]})
        except ValueError as e:
            self._json({"error": str(e), "ok": False}, status=422)
        except Exception as e:
            self._json({"error": str(e), "ok": False}, status=500)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self._json({"error": "Fichier non trouvé"}, status=404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(data))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    print(f"\nFactuel serveur — http://localhost:{args.port}")
    print(f"  GET  /api/articles  → liste des articles")
    print(f"  POST /api/generate  → {{\"sujet\": \"...\"}}")
    print(f"  CTRL+C pour arrêter\n")

    server = HTTPServer(("0.0.0.0", args.port), FactuelHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
