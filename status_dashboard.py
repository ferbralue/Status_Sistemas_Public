#!/usr/bin/env python3
"""
Dashboard de status: verifica se o sistema web e o backend do app mobile estão online
e gera um arquivo dashboard.html.

Uso:
    python3 status_dashboard.py              # verifica uma vez e gera o HTML
    python3 status_dashboard.py --watch 60   # verifica a cada 60s (Ctrl+C para parar)

Requer apenas Python 3.8+ (biblioteca padrão).
"""
import argparse
import json
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib import error, request

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO: edite aqui
# ----------------------------------------------------------------------------
SYSTEMS = [
    {
        "name": "Multi Gestão",
        "kind": "Web",
        "url": "https://multigestaodoc.com.br/auth/sign-in",          # <- troque pela URL real
        "expect": 200,                            # código HTTP esperado
    },
    {
        "name": "Estoca Fácil",
        "kind": "API do app",
        # O app roda no celular, então checamos o backend/API que ele usa.
        # Ideal: um endpoint de health, ex.: /health ou /api/status
        "url": "https://api.exemplo.com.br/health",  # <- troque pela URL real
        "expect": 200,
    },
]

TIMEOUT_S = 10          # tempo máximo de espera por resposta
SLOW_MS = 2000          # acima disso o status vira "lento"
MAX_HISTORY = 100       # quantas verificações guardar por sistema
OUTPUT_FILE = Path("dashboard.html")
HISTORY_FILE = Path("status_history.json")
# ----------------------------------------------------------------------------


def check(system):
    """Faz uma requisição e devolve o resultado da verificação."""
    req = request.Request(system["url"], headers={"User-Agent": "status-dashboard/1.0"})
    start = time.perf_counter()
    code, err = None, None
    try:
        with request.urlopen(req, timeout=TIMEOUT_S) as resp:
            code = resp.status
    except error.HTTPError as e:      # 4xx / 5xx ainda são respostas do servidor
        code = e.code
    except Exception as e:            # DNS, timeout, conexão recusada, SSL...
        err = str(getattr(e, "reason", e)) or e.__class__.__name__
    ms = round((time.perf_counter() - start) * 1000)

    if code is None or code != system.get("expect", 200):
        state = "down"
        if err is None:
            err = f"Esperado HTTP {system.get('expect', 200)}, recebido {code}"
    elif ms > SLOW_MS:
        state = "slow"
    else:
        state = "up"

    return {
        "t": datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "code": code,
        "ms": ms,
        "error": err,
    }


def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")


LABELS = {"up": "Online", "slow": "Lento", "down": "Offline"}


def render(results, history):
    cards = []
    for system, res in results:
        past = history.get(system["name"], [])
        ok = sum(1 for h in past if h["state"] in ("up", "slow"))
        uptime = f"{ok / len(past) * 100:.1f}%" if past else "–"
        bars = "".join(
            f'<i class="b {h["state"]}" title="{escape(h["t"])} · {LABELS[h["state"]]}"></i>'
            for h in past[-40:]
        )
        code = res["code"] if res["code"] is not None else "–"
        err = f'<p class="err">{escape(res["error"])}</p>' if res["error"] else ""
        cards.append(f"""
        <section class="card">
          <div class="top">
            <div><h2>{escape(system["name"])}</h2><span class="kind">{escape(system["kind"])}</span></div>
            <span class="pill {res["state"]}">{LABELS[res["state"]]}</span>
          </div>
          <p class="url">{escape(system["url"])}</p>
          <dl>
            <div><dt>Resposta</dt><dd>{res["ms"]} ms</dd></div>
            <div><dt>HTTP</dt><dd>{code}</dd></div>
            <div><dt>Disponibilidade</dt><dd>{uptime}</dd></div>
          </dl>
          <div class="bars">{bars}</div>
          {err}
        </section>""")

    states = [r["state"] for _, r in results]
    if all(s == "up" for s in states):
        banner, cls = "Todos os sistemas estão operando normalmente", "up"
    elif all(s == "down" for s in states):
        banner, cls = "Todos os sistemas estão fora do ar", "down"
    elif "down" in states:
        banner, cls = "Um ou mais sistemas estão fora do ar", "down"
    else:
        banner, cls = "Sistemas online, mas com lentidão", "slow"

    updated = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return (
        TEMPLATE.replace("__BANNER__", banner)
        .replace("__BCLS__", cls)
        .replace("__CARDS__", "".join(cards))
        .replace("__UPDATED__", updated)
    )


def run_once():
    history = load_history()
    results = []
    for system in SYSTEMS:
        res = check(system)
        results.append((system, res))
        h = history.setdefault(system["name"], [])
        h.append(res)
        del h[:-MAX_HISTORY]
        print(f'[{res["t"]}] {system["name"]}: {LABELS[res["state"]]} ({res["ms"]} ms)'
              + (f' – {res["error"]}' if res["error"] else ""))
    save_history(history)
    OUTPUT_FILE.write_text(render(results, history), encoding="utf-8")
    return all(r["state"] != "down" for _, r in results)


def main():
    parser = argparse.ArgumentParser(description="Dashboard de status web + app mobile")
    parser.add_argument("--watch", type=int, metavar="SEGUNDOS",
                        help="repete a verificação a cada N segundos")
    args = parser.parse_args()

    if not args.watch:
        healthy = run_once()
        print(f"Dashboard gerado em {OUTPUT_FILE.resolve()}")
        sys.exit(0 if healthy else 1)   # útil em cron/CI

    print(f"Monitorando a cada {args.watch}s. Abra {OUTPUT_FILE.resolve()} no navegador.")
    try:
        while True:
            run_once()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print("\nEncerrado.")


TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Status dos sistemas</title>
<style>
  :root{--bg:#f5f6f8;--card:#fff;--text:#1b1f24;--muted:#6b7280;--line:#e5e7eb;
        --up:#16a34a;--slow:#d97706;--down:#dc2626;--upbg:#dcfce7;--slowbg:#fef3c7;--downbg:#fee2e2}
  @media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#181c22;--text:#e6e8eb;--muted:#9aa3ad;--line:#2a3038;
        --upbg:#12331f;--slowbg:#3a2a0c;--downbg:#3d1616}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:24px}
  main{max-width:900px;margin:0 auto}
  h1{font-size:22px;margin:0 0 16px}
  .banner{padding:14px 18px;border-radius:12px;font-weight:600;margin-bottom:20px}
  .banner.up{background:var(--upbg);color:var(--up)}
  .banner.slow{background:var(--slowbg);color:var(--slow)}
  .banner.down{background:var(--downbg);color:var(--down)}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
  .top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
  h2{font-size:18px;margin:0}
  .kind{font-size:13px;color:var(--muted)}
  .pill{padding:4px 12px;border-radius:999px;font-size:13px;font-weight:600}
  .pill.up{background:var(--upbg);color:var(--up)}
  .pill.slow{background:var(--slowbg);color:var(--slow)}
  .pill.down{background:var(--downbg);color:var(--down)}
  .url{color:var(--muted);font-size:13px;word-break:break-all;margin:10px 0 14px}
  dl{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 14px}
  dt{font-size:12px;color:var(--muted)} dd{margin:0;font-weight:600}
  .bars{display:flex;gap:3px;height:28px;align-items:stretch}
  .b{flex:1;border-radius:2px;background:var(--line);max-width:10px}
  .b.up{background:var(--up)} .b.slow{background:var(--slow)} .b.down{background:var(--down)}
  .err{margin:12px 0 0;font-size:13px;color:var(--down)}
  footer{margin-top:20px;font-size:13px;color:var(--muted)}
</style>
</head>
<body>
<main>
  <h1>Status dos sistemas</h1>
  <div class="banner __BCLS__">__BANNER__</div>
  <div class="grid">__CARDS__</div>
  <footer>Última verificação: __UPDATED__ · a página recarrega sozinha a cada 30s</footer>
</main>
</body>
</html>
"""

if __name__ == "__main__":
    main()
