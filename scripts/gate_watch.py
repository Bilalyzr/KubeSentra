"""Phase 7 live-gate driver: waits for the approval pause, submits the
edited rollout_undo decision, then follows execution -> verification ->
postmortem to the terminal state. Usage:
    python scripts/gate_watch.py            # full cycle (needs fault injected)
    python scripts/gate_watch.py --watch    # only wait for the pause
"""
import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8547"
TOKEN = "kubesentra-dev-approval"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def post(path: str, body: dict, token: str | None = None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Approval-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def find_incident():
    data = get("/incidents?limit=20")
    for inc in data["incidents"]:
        if inc["service"] == "checkoutservice" and inc["status"] != "resolved":
            return inc
    return None


def wait_pause(timeout_s=1500):
    print("waiting for approval pause...")
    start = time.time()
    while time.time() - start < timeout_s:
        inc = find_incident()
        if inc:
            print(f"  t+{int(time.time()-start)}s status={inc['status']}")
            if inc["status"] in ("awaiting_approval", "failed", "escalated"):
                return inc
        else:
            print(f"  t+{int(time.time()-start)}s no incident yet")
        time.sleep(20)
    raise SystemExit("timeout waiting for pause")


EDITED_PLAN = [{
    "name": "rollout_undo", "namespace": "boutique",
    "target": "checkoutservice", "params": {}, "risk": "low",
    "rationale": "restore previous revision with working 128Mi limit",
}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    inc = wait_pause()
    if inc["status"] != "awaiting_approval":
        print(f"terminal without approval: {inc['status']}")
        return
    print(f"paused incident: {inc['id']}")
    print(f"root cause: {(inc.get('root_cause') or '')[:140]}")

    if args.watch:
        return

    # 1. invalid edit first (gate check) -> expect 400
    bad = [dict(EDITED_PLAN[0], name="scale", params={"replicas": 99})]
    code, body = post(f"/incidents/{inc['id']}/decision",
                      {"status": "edited", "plan": bad, "approver": "gate"},
                      TOKEN)
    print(f"invalid edit -> HTTP {code}: {json.dumps(body)[:160]}")
    assert code == 400, "invalid edit must be rejected"

    # 2. valid edited rollout_undo -> approve and RUN
    code, body = post(f"/incidents/{inc['id']}/decision",
                      {"status": "edited", "plan": EDITED_PLAN,
                       "approver": "gate"}, TOKEN)
    print(f"valid edit -> HTTP {code}: {json.dumps(body)[:160]}")
    assert code == 200, body

    # 3. follow to terminal (execute -> verify -> postmortem)
    for i in range(60):
        time.sleep(20)
        cur = get(f"/incidents/{inc['id']}")
        print(f"  t+{(i+1)*20}s status={cur['status']}")
        if cur["status"] in ("resolved", "failed", "escalated"):
            break

    final = get(f"/incidents/{inc['id']}")
    print("=== FINAL ===")
    print("status:", final["status"], "| resolved:", final["resolved"])
    print("root_cause:", (final.get("root_cause") or "")[:160])
    pm = final.get("summary") or ""
    try:
        doc = json.loads(pm)
        print("verdict:", doc.get("verification"))
        print("checks:", json.dumps(doc.get("verification_checks", {}))[:220])
        rem = doc.get("remediation") or {}
        print("executed:", rem.get("executed"))
        for r in rem.get("results", []):
            print("  result:", r.get("action"), r.get("ok"),
                  (r.get("detail") or "")[:110])
        print("approval:", json.dumps(doc.get("approval"))[:180])
        print("lessons:", (doc.get("lessons_learned") or [])[:2])
    except json.JSONDecodeError:
        print("summary(raw):", pm[:300])


if __name__ == "__main__":
    main()
