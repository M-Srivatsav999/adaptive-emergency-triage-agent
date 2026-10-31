"""metrics.py - tiny in-process counters rendered in Prometheus text format (no dependencies, no patient data)."""
import threading
import time

_lock = threading.Lock()
_counters = {}
_started = time.time()

HELP = {
    "http_requests_total": "HTTP requests by path group and status",
    "rate_limited_total": "Requests rejected by the rate limiter",
    "login_failures_total": "Failed logins",
    "accounts_created_total": "Self-registered accounts created",
    "triage_results_total": "Completed triage results by urgency",
    "triage_red_flag_total": "Results where the emergency red-flag layer fired",
    "triage_low_confidence_total": "Results where the tool declined to name a condition",
    "ai_mode_total": "Which engine produced the wording (live_model / built_in_rules / mixed)",
}


def inc(name: str, **labels) -> None:
    key = (name, tuple(sorted(labels.items())))
    with _lock:
        _counters[key] = _counters.get(key, 0) + 1


def snapshot() -> dict:
    with _lock:
        out = {}
        for (name, labels), v in _counters.items():
            out.setdefault(name, []).append({"labels": dict(labels), "value": v})
        return out


def reset() -> None:   # tests
    with _lock:
        _counters.clear()


def render() -> str:
    lines = [f"# HELP triage_uptime_seconds Seconds since start", "# TYPE triage_uptime_seconds gauge",
             f"triage_uptime_seconds {int(time.time() - _started)}"]
    with _lock:
        names = sorted({n for n, _ in _counters})
        for n in names:
            lines.append(f"# HELP triage_{n} {HELP.get(n, n)}")
            lines.append(f"# TYPE triage_{n} counter")
            for (name, labels), v in sorted(_counters.items()):
                if name == n:
                    lab = ",".join(f'{k}="{val}"' for k, val in labels)
                    lines.append(f"triage_{n}{{{lab}}} {v}" if lab else f"triage_{n} {v}")
    return "\n".join(lines) + "\n"
