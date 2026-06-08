#!/usr/bin/env python3
"""
State- & Report-Helfer für den Deploy-&-Test-Workflow.

Hält docs/deploy-test/state.json: pro (Instanz, CheckId) das letzte Ergebnis +
den Image-Tag/Commit, gegen den es verifiziert wurde. Daraus berechnet `plan`,
welche teuren Tier-2-Browser-Checks erneut laufen MÜSSEN und welche man skippen
darf (grün + unveränderte Code-Surface) — damit teure Frontend-Tests nicht jedes
Release neu durchlaufen.

Subcommands:
  record   <instance> <checkId> <result> --tag T [--commit C] [--note "..."]
  plan     <instance> --tag T [--commit C] [--base-commit B] [--features k=v,k=v]
  report   <instance> --tag T [--out FILE]
  show     <instance>

result ∈ pass | fail | na | skip
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone

# Windows-Console ist cp1252 -> ✅/⏭/⚪ würden beim Drucken crashen. UTF-8 erzwingen
# (Console-Mojibake ist ein Display-Bug, kein Datenbug -> Encoding fixen, nicht Zeichen strippen).
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)               # docs/deploy-test
STATE = os.path.join(ROOT, "state.json")
CHECKS = os.path.join(ROOT, "checks.json")


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _checks():
    return {c["id"]: c for c in _load(CHECKS, {"checks": []})["checks"]}


def _state():
    return _load(STATE, {"instances": {}})


def _changed_files(base, head):
    """Geänderte Dateien zwischen zwei Commits (relativ zum Repo-Root). Leer/None -> None (konservativ: alles neu testen)."""
    if not base or not head:
        return None
    try:
        repo = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        out = subprocess.check_output(["git", "-C", repo, "diff", "--name-only", f"{base}..{head}"], text=True)
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return None


def _surface_hit(surface, changed):
    if "*" in surface:
        return True
    if changed is None:
        return True  # unbekannt -> konservativ laufen lassen
    for f in changed:
        for s in surface:
            if f.startswith(s.rstrip("/")):
                return True
    return False


def cmd_record(a):
    st = _state()
    inst = st["instances"].setdefault(a.instance, {"checks": {}})
    inst["checks"][a.checkId] = {
        "result": a.result,
        "tag": a.tag,
        "commit": a.commit or "",
        "note": a.note or "",
        "at": _now(),
    }
    _save(STATE, st)
    print(f"recorded {a.instance}/{a.checkId} = {a.result} @ {a.tag}")


def cmd_plan(a):
    checks = _checks()
    st = _state().get("instances", {}).get(a.instance, {}).get("checks", {})
    feats = {}
    if a.features:
        for kv in a.features.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                feats[k.strip()] = v.strip().lower() in ("1", "true", "yes")
    # base-commit: woran der letzte grüne Lauf hing (häufigster Tag in state) — oder explizit übergeben
    base = a.base_commit
    changed = _changed_files(base, a.commit)

    run, skip, na = [], [], []
    for cid, c in checks.items():
        if c["tier"] != 2:
            continue
        gate = c.get("gate_features", [])
        if gate and not all(feats.get(g, False) for g in gate):
            na.append((cid, c["name"], "feature-gated off: " + "+".join(gate)))
            continue
        prev = st.get(cid)
        if prev and prev.get("result") == "pass" and prev.get("tag") and not _surface_hit(c["surface"], changed):
            skip.append((cid, c["name"], f"grün @ {prev['tag']}, Surface unverändert"))
        else:
            if not (prev and prev.get("result") == "pass"):
                why = "noch nie grün"
            elif changed is None:
                why = "konservativ (kein base-commit)"
            else:
                why = "Surface geändert"
            run.append((cid, c["name"], why))

    print(f"## Tier-2 Plan für {a.instance} @ {a.tag}")
    print(f"   (changed files: {'unbekannt -> alles laufen' if changed is None else len(changed)})\n")
    print(f"RUN ({len(run)}):")
    for cid, n, w in run:
        print(f"  ▶ {cid:14} {n}  [{w}]")
    print(f"\nSKIP ({len(skip)}):")
    for cid, n, w in skip:
        print(f"  ⏭ {cid:14} {n}  [{w}]")
    print(f"\nN/A ({len(na)}):")
    for cid, n, w in na:
        print(f"  ⚪ {cid:14} {n}  [{w}]")


def cmd_report(a):
    checks = _checks()
    st = _state().get("instances", {}).get(a.instance, {}).get("checks", {})
    lines = []
    lines.append(f"# Deploy-Test-Report — {a.instance} @ `{a.tag}`")
    lines.append("")
    lines.append(f"- Erzeugt: {_now()}")
    lines.append(f"- Instanz: `{a.instance}`")
    lines.append(f"- Image-Tag: `{a.tag}`")
    lines.append("")
    lines.append("| Check | Tier | Ergebnis | Verifiziert @ | Notiz |")
    lines.append("|-------|------|----------|---------------|-------|")
    icon = {"pass": "✅", "fail": "❌", "na": "⚪", "skip": "⏭"}
    for cid, c in sorted(checks.items(), key=lambda x: (x[1]["tier"], x[0])):
        r = st.get(cid, {})
        res = r.get("result", "—")
        lines.append(f"| {cid} — {c['name']} | T{c['tier']} | {icon.get(res, '—')} {res} | `{r.get('tag','—')}` | {r.get('note','')} |")
    npass = sum(1 for r in st.values() if r.get("result") == "pass")
    nfail = sum(1 for r in st.values() if r.get("result") == "fail")
    lines.append("")
    lines.append(f"**Summe:** {npass} pass · {nfail} fail · {len(checks)} Checks gesamt")
    if nfail:
        lines.append("")
        lines.append("> ⚠️ FAIL vorhanden — Ursache belegen (Pod-Logs + Route-Console), kein \"sollte gehen\".")
    out = "\n".join(lines) + "\n"
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"report -> {a.out}")
    else:
        print(out)


def cmd_show(a):
    st = _state().get("instances", {}).get(a.instance, {}).get("checks", {})
    print(json.dumps(st, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record"); r.add_argument("instance"); r.add_argument("checkId")
    r.add_argument("result", choices=["pass", "fail", "na", "skip"])
    r.add_argument("--tag", required=True); r.add_argument("--commit"); r.add_argument("--note")
    r.set_defaults(func=cmd_record)

    pl = sub.add_parser("plan"); pl.add_argument("instance"); pl.add_argument("--tag", required=True)
    pl.add_argument("--commit"); pl.add_argument("--base-commit", dest="base_commit"); pl.add_argument("--features")
    pl.set_defaults(func=cmd_plan)

    rp = sub.add_parser("report"); rp.add_argument("instance"); rp.add_argument("--tag", required=True); rp.add_argument("--out")
    rp.set_defaults(func=cmd_report)

    sh = sub.add_parser("show"); sh.add_argument("instance"); sh.set_defaults(func=cmd_show)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
