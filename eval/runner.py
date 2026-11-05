"""Scenario runner: drives one fault scenario end to end through the REAL
pipeline (inject -> Alertmanager alert -> webhook -> investigation ->
auto-approval for evaluation -> execution -> verification -> cleanup),
then records measured metrics. No step is simulated.

Usage (API must be running with the desired INVESTIGATION_MODE):
    python -m eval.runner --scenario oom_checkout --config multi_agent
    python -m eval.runner --scenario all --config b0   # rule baseline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "eval" / "scenarios"
RESULTS_DIR = ROOT / "eval" / "results"
BASE = "http://127.0.0.1:8547"
TOKEN = "kubesentra-dev-approval"

# Python's plain `bash` can resolve to a foreign shell with its own kubectl
# and HOME (found live: HOME=/home/billu). Always use the real Git bash.
GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"


def sh(cmd: list[str]) -> str:
    if cmd and cmd[0] == "bash":
        cmd = [GIT_BASH, *cmd[1:]]
    # fault cleanup waits for a full rollout (its own --timeout=300s) plus
    # image pulls on a slow network - give the wrapper generous headroom
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                         cwd=str(ROOT))
    if out.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {out.stderr[:300]}")
    return out.stdout

# B0 rule baseline: alert-name -> fixed diagnosis (no LLM anywhere)
RULES = {
    "PodRestarting": {"category": "resource",
                      "cause": "container restarting repeatedly (OOMKilled "
                               "or crash); check limits and last rollout"},
    "PodNotReady": {"category": "config",
                    "cause": "pod not passing readiness; check probe config "
                             "and recent rollout"},
    "DeploymentReplicasUnavailable": {"category": "application",
                                      "cause": "unavailable replicas; check "
                                               "pod status and events"},
    "CPUThrottlingHigh": {"category": "resource",
                          "cause": "CPU limit too low for the workload"},
    "HighErrorRate": {"category": "dependency",
                      "cause": "elevated 5xx; check downstream services"},
}


def api(path: str, timeout: float = 30.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read())


def post_decision(incident_id: str, status: str, plan, approver: str):
    req = urllib.request.Request(
        f"{BASE}/incidents/{incident_id}/decision",
        data=json.dumps({"status": status, "plan": plan,
                         "approver": approver}).encode(),
        headers={"Content-Type": "application/json",
                 "X-Approval-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def scenario_names() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))


def wait_for(predicate, timeout_s: int, every_s: int = 20, label=""):
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            value = predicate()
            if value is not None:
                return value
        except Exception:  # noqa: BLE001
            pass
        time.sleep(every_s)
    raise TimeoutError(f"timeout waiting for {label}")


def lab_healthy() -> bool:
    try:
        pods = sh(["kubectl", "-n", "boutique", "get", "deploy",
                   "--no-headers"])
        bad = [ln for ln in pods.splitlines()
               if ln and ln.split()[1] != ln.split()[2]]
        # deployment availability column format: current/desired
        ready = sh(["kubectl", "-n", "boutique", "get", "deploy",
                    "-o", "jsonpath={.items[*].status.readyReplicas}"]).split()
        desired = sh(["kubectl", "-n", "boutique", "get", "deploy",
                      "-o", "jsonpath={.items[*].status.replicas}"]).split()
        return len(ready) == len(desired) > 0
    except Exception:  # noqa: BLE001
        return False


def find_incident(service: str, since_iso: str | None = None) -> dict | None:
    """Newest non-terminal incident for the service, optionally only ones
    created after `since_iso` (prevents matching stale rows from earlier
    runs). NB: the API renders created_at with a SPACE separator; since_iso
    from datetime.isoformat() uses 'T' - normalize before comparing."""
    for inc in api("/incidents?limit=20")["incidents"]:
        if (inc["service"] == service
                and inc["status"] not in ("resolved", "rejected", "diagnosed",
                                          "approved")
                and (since_iso is None
                     or inc["created_at"] >= since_iso.replace("T", " "))):
            return inc
    return None


def run_b0(scenario: dict) -> dict:
    """Rule baseline: read the alert name, apply the fixed rule. No LLM."""
    expected_alerts = scenario["expected_alerts"]
    rule = RULES.get(expected_alerts[0], {"category": "other",
                                          "cause": "no rule matched"})
    gt = scenario["ground_truth"]
    top1 = (rule["category"] == gt["category"])
    return {
        "scenario": scenario["id"], "config": "b0_rule",
        "top1_correct": top1, "top3_correct": top1,  # single answer
        "category_predicted": rule["category"],
        "root_cause": rule["cause"],
        "time_to_diagnosis_s": 1,  # rule lookup ~instant
        "remediation_success": None,  # B0 proposes no action
        "unauthorized_writes": 0, "evidence_grounded": False,
        "llm_cost_usd": 0.0, "steps": 0, "note": "rule baseline (no LLM)",
    }


def run_scenario(scenario: dict, config: str, auto_approve: bool = True) -> dict:
    name = scenario["id"]
    service = scenario["target"]["deployment"]

    # 0. health gate + best-effort clean slate for this service
    if not lab_healthy():
        raise RuntimeError("lab not healthy - run scripts/lab_health.sh")
    try:
        sh(["bash", "scripts/cleanup_fault.sh", name])
    except Exception as exc:  # noqa: BLE001 - hygiene only; health gate passed
        print(f"  pre-cleanup best-effort: {exc}")

    started = time.time()
    since_iso = datetime.now(timezone.utc).isoformat()
    # 1. inject
    sh(["bash", "scripts/inject_fault.sh", name])
    try:
        # 2. wait for the incident to appear (real Alertmanager -> webhook)
        inc = wait_for(lambda: find_incident(service, since_iso),
                       timeout_s=900, label="incident creation")
        incident_id = inc["id"]

        # 3. wait for diagnosis (awaiting_approval / diagnosed / terminal)
        def terminal():
            cur = api(f"/incidents/{incident_id}")
            if cur["status"] in ("awaiting_approval", "diagnosed",
                                 "failed", "escalated", "resolved",
                                 "approved"):
                return cur
            return None

        cur = wait_for(terminal, timeout_s=1400, label="diagnosis")
        ttd = cur.get("time_to_diagnosis_s") or int(time.time() - started)

        record = {
            "scenario": name, "config": config,
            "incident_id": incident_id,
            "status": cur["status"],
            "top1_correct": None, "top3_correct": None,
            "category_predicted": cur.get("root_cause_category"),
            "root_cause": cur.get("root_cause"),
            "time_to_diagnosis_s": ttd,
            "remediation_success": None,
            "verdict": None, "unauthorized_writes": 0,
            "evidence_grounded": None, "llm_cost_usd": None,
            "steps": None, "judge": None,
        }

        # 4. judge the diagnosis against ground truth (LLM judge)
        from eval.judge import judge_diagnosis
        record.update(judge_diagnosis(scenario, cur))

        # 5. auto-approve for evaluation (real endpoint, recorded approver)
        if auto_approve and cur["status"] == "awaiting_approval":
            payload = (cur.get("actions") or {}).get(
                "approval_payload", {}) if isinstance(cur.get("actions"),
                                                      dict) else {}
            plan = payload.get("plan") or []
            if plan:
                code, body = post_decision(incident_id, "approved", None,
                                           f"eval-{config}")
                record["approve_http"] = code
                if code == 200:
                    final = wait_for(
                        lambda: (lambda c: c if c["status"] in
                                 ("resolved", "failed", "escalated")
                                 else None)(api(f"/incidents/{incident_id}")),
                        timeout_s=900, label="execution+verification")
                    pm = api(f"/incidents/{incident_id}/postmortem")
                    doc = pm.get("postmortem") or {}
                    record["verdict"] = doc.get("verification")
                    record["remediation_success"] = (
                        doc.get("verification") == "RESOLVED")
            else:
                # empty plan: reject to close the loop honestly
                post_decision(incident_id, "rejected", None, f"eval-{config}")
                record["approve_http"] = "empty-plan-rejected"

        # 6. grounding: does the recorded summary cite evidence IDs?
        summary = cur.get("summary") or ""
        record["evidence_grounded"] = ("evidence:" in summary
                                       or "E1" in summary or "E2" in summary)
        # steps from persisted timeline
        actions = cur.get("actions")
        if isinstance(actions, dict):
            record["steps"] = len(actions.get("timeline", []))
        return record
    finally:
        subprocess.run([GIT_BASH, "scripts/cleanup_fault.sh", name],
                       capture_output=True, text=True, timeout=600,
                       cwd=str(ROOT))


def append_result(record: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = RESULTS_DIR / f"{record['config']}_{record['scenario']}_{stamp}.json"
    path.write_text(json.dumps(record, indent=1, default=str),
                    encoding="utf-8")
    print(f"  result -> {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True,
                        help="scenario id or 'all'")
    parser.add_argument("--config", default="multi_agent",
                        choices=["multi_agent", "baseline", "b0_rule",
                                 "memory_off", "rag_off",
                                 "multi_agent_e5inject"])
    args = parser.parse_args()

    names = scenario_names() if args.scenario == "all" else [args.scenario]
    for name in names:
        scenario = load_scenario(name)
        print(f"[eval] {name} [{args.config}]")
        try:
            if args.config == "b0_rule":
                record = run_b0(scenario)
            else:
                record = run_scenario(scenario, args.config)
            print(f"  top1={record.get('top1_correct')} "
                  f"ttd={record.get('time_to_diagnosis_s')}s "
                  f"verdict={record.get('verdict')}")
            append_result(record)
        except Exception as exc:  # noqa: BLE001 - record failures honestly
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            append_result({"scenario": name, "config": args.config,
                           "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
