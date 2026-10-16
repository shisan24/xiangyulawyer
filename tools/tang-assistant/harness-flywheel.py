#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
harness-flywheel.py — Harness 数据飞轮

Reads all evaluation results, computes trends, detects regressions,
and generates actionable feedback.

Usage:
  python harness-flywheel.py              # Full report
  python harness-flywheel.py --alerts-only  # Only regression alerts (for cron)
  python harness-flywheel.py --skill <name> # Single skill trend
  python harness-flywheel.py --dashboard    # Summary dashboard
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path(os.environ.get("HARNESS_DIR", Path.home() / ".harness"))
RESULTS_DIR = HARNESS_DIR / "results"
REGRESSION_THRESHOLD = 3.0  # % drop triggers alert


def load_all_results():
    """Load all evaluation result JSON files."""
    all_results = defaultdict(list)
    if not RESULTS_DIR.exists():
        return all_results

    for f in sorted(RESULTS_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)

            # Extract skill name from filename: "<skill>-judge-<ts>.json"
            fname = f.stem
            skill = fname.split("-judge-")[0]

            if isinstance(data, list):
                for r in data:
                    sd = r.get("score_data", {})
                    overall = sd.get("overall_score", 0)
                    if overall == 0:
                        continue
                    tc = r.get("test_case", "?")
                    ts = r.get("timestamp", "")[:19]
                    all_results[skill].append({
                        "test_case": tc,
                        "score": overall,
                        "timestamp": ts,
                        "file": f.name,
                    })
            elif isinstance(data, dict):
                overall = data.get("score_data", {}).get("overall_score", 0)
                if overall > 0:
                    all_results[skill].append({
                        "test_case": "?",
                        "score": overall,
                        "timestamp": data.get("timestamp", "")[:19],
                        "file": f.name,
                    })
        except Exception:
            continue

    return all_results


def compute_trend(scores):
    """Compute trend: latest, previous, delta, direction."""
    if len(scores) < 2:
        return {
            "latest": scores[-1]["score"] if scores else 0,
            "previous": None,
            "delta": 0,
            "direction": "flat",
            "runs": len(scores),
        }

    latest = scores[-1]["score"]
    previous = scores[-2]["score"]
    delta = latest - previous
    pct = (delta / previous * 100) if previous > 0 else 0

    direction = "up" if pct > 1 else "down" if pct < -1 else "flat"
    regression = pct < -REGRESSION_THRESHOLD

    return {
        "latest": latest,
        "previous": previous,
        "delta": round(delta, 1),
        "delta_pct": round(pct, 1),
        "direction": direction,
        "regression": regression,
        "runs": len(scores),
        "all_scores": [s["score"] for s in scores],
    }


def analyze_all():
    """Full analysis of all results."""
    all_results = load_all_results()
    if not all_results:
        return {"error": "no results found"}

    analysis = {}
    alerts = []
    total_skills = len(all_results)

    for skill, results in sorted(all_results.items()):
        trend = compute_trend(results)
        analysis[skill] = trend

        if trend["regression"]:
            alerts.append({
                "skill": skill,
                "latest": trend["latest"],
                "previous": trend["previous"],
                "delta_pct": trend["delta_pct"],
            })

    # Overall health
    latest_scores = [a["latest"] for a in analysis.values() if a["latest"] > 0]
    avg_score = sum(latest_scores) / len(latest_scores) if latest_scores else 0

    return {
        "timestamp": datetime.now().isoformat(),
        "skills_analyzed": total_skills,
        "total_evaluations": sum(a["runs"] for a in analysis.values()),
        "average_score": round(avg_score, 1),
        "regression_alerts": len(alerts),
        "alerts": alerts,
        "skills": analysis,
    }


def dashboard():
    """Print a compact dashboard."""
    result = analyze_all()
    if "error" in result:
        print(result["error"])
        return

    print(f"\n{'='*60}")
    print(f"  Harness 飞轮 — {result['timestamp'][:10]}")
    print(f"{'='*60}")
    print(f"  技能数: {result['skills_analyzed']}  评测次数: {result['total_evaluations']}  平均分: {result['average_score']}")
    print(f"  回归告警: {result['regression_alerts']}")
    print(f"{'='*60}\n")

    lines = []
    for skill, trend in sorted(result["skills"].items()):
        arrow = "↑" if trend["direction"] == "up" else "↓" if trend["direction"] == "down" else "→"
        flag = " ⚠ REGRESSION" if trend["regression"] else ""
        prev_str = f" (前 {trend['previous']})" if trend["previous"] else ""
        lines.append(f"  {skill:32s} {trend['latest']:5.1f} {arrow} {trend['delta_pct']:+5.1f}%{prev_str}{flag}")

    for line in sorted(lines):
        print(line)

    print(f"\n  分数趋势: {', '.join(str(s) for s in result['skills'].get('architecture-design', {}).get('all_scores', []))}")

    if result["alerts"]:
        print(f"\n  ⚠ 回归告警:")
        for a in result["alerts"]:
            print(f"    {a['skill']}: {a['previous']} → {a['latest']} ({a['delta_pct']:+.1f}%)")


def alerts_only():
    """Output only regression alerts (for cron)."""
    result = analyze_all()
    if "error" in result:
        return

    if result["regression_alerts"] == 0:
        return  # Silent when healthy

    print(f"⚠ Harness Regression Alert — {result['timestamp'][:10]}")
    for a in result["alerts"]:
        print(f"  {a['skill']}: {a['previous']} → {a['latest']} ({a['delta_pct']:+.1f}%)")


def single_skill(skill_name):
    """Detailed trend for one skill."""
    all_results = load_all_results()
    if skill_name not in all_results:
        print(f"Skill '{skill_name}' not found. Available: {list(all_results.keys())}")
        return

    results = all_results[skill_name]
    trend = compute_trend(results)

    print(f"\n  {skill_name} — {trend['runs']} 次评测")
    print(f"  {'─'*40}")
    for i, r in enumerate(results):
        marker = " ← latest" if i == len(results) - 1 else ""
        print(f"  {i+1}. [{r['test_case']}] {r['score']:.1f}  {r['timestamp'][:16]}{marker}")
    print(f"  {'─'*40}")
    print(f"  最新: {trend['latest']:.1f}  前次: {trend['previous']}  变化: {trend['delta_pct']:+.1f}%  {trend['direction']}")
    if trend["regression"]:
        print(f"  ⚠ 回归告警: 下降超过 {REGRESSION_THRESHOLD}%")


def main():
    parser = argparse.ArgumentParser(description="Harness 数据飞轮 — 评分趋势 + 回归检测 + 反馈")
    parser.add_argument("--alerts-only", action="store_true", help="Only regression alerts (for cron, silent if healthy)")
    parser.add_argument("--skill", help="Single skill trend")
    parser.add_argument("--dashboard", action="store_true", help="Compact dashboard")
    parser.add_argument("--json", action="store_true", help="Output full analysis as JSON")
    args = parser.parse_args()

    if args.alerts_only:
        alerts_only()
    elif args.skill:
        single_skill(args.skill)
    elif args.json:
        result = analyze_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        dashboard()


if __name__ == "__main__":
    main()
