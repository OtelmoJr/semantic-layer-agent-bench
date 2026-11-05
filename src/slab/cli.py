"""`slab` command line: data, gold-check, parity, bench, report, aa."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="slab", description="Semantic Layer Agent Bench")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("data", help="generate TPC-H and load DuckDB")
    d.add_argument("--sf", type=float, default=None)
    d.add_argument("--force", action="store_true")

    sub.add_parser("gold-check", help="validate the gold set and its frozen hash")
    p = sub.add_parser("parity", help="semantic layer vs reference SQL")
    p.add_argument("ids", nargs="*")
    p.add_argument("-v", "--verbose", action="store_true")

    b = sub.add_parser("bench", help="run the benchmark")
    b.add_argument("--provider", required=True, choices=["stub", "ollama", "anthropic"])
    b.add_argument("--model")
    b.add_argument("--arms", default="A,B,C")
    b.add_argument("--split", default="holdout", choices=["dev", "holdout", "all"])
    b.add_argument("--attempts", type=int, default=3)
    b.add_argument("--ids", default="", help="comma-separated question ids (overrides --split)")
    b.add_argument("--run-id")
    b.add_argument("--transport", default="stdio", choices=["stdio", "inproc"])
    b.add_argument("--budget-usd", type=float)

    r = sub.add_parser("report", help="build report.md from one or more runs")
    r.add_argument("run_ids", nargs="+")
    r.add_argument("--split", default="holdout", choices=["dev", "holdout", "all"])
    r.add_argument("--out")

    a = sub.add_parser("aa", help="A/A test: same arm, two runs, expect no significant difference")
    a.add_argument("run_a")
    a.add_argument("run_b")
    a.add_argument("--arm", default="A")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        stream=sys.stderr)
    for noisy in ("httpx", "mcp", "dbt", "metricflow", "metricflow_semantics"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "data":
        from slab import config
        from slab.data.generate import build

        build(args.sf if args.sf is not None else config.SCALE_FACTOR, args.force)
    elif args.cmd == "gold-check":
        from slab.gold import main as gold_main

        gold_main([])
    elif args.cmd == "parity":
        from slab.parity import main as parity_main

        parity_main(args.ids + (["-v"] if args.verbose else []))
    elif args.cmd == "bench":
        from slab.harness.runner import RunConfig, run_sync

        run_id = args.run_id or f"{args.provider}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        cfg = RunConfig(
            run_id=run_id, provider=args.provider, model=args.model,
            arms=tuple(x.strip().upper() for x in args.arms.split(",") if x.strip()),
            split=args.split, attempts=args.attempts,
            ids=tuple(x.strip() for x in args.ids.split(",") if x.strip()),
            transport=args.transport, budget_usd=args.budget_usd,
        )
        m = run_sync(cfg)
        print(f"run {m['run_id']} finished: {m['questions']} questions x {len(m['arms'])} arms x {m['attempts']}")
    elif args.cmd == "report":
        from pathlib import Path

        from slab.harness.report import build, default_out

        out = Path(args.out) if args.out else default_out(args.run_ids)
        path = build(args.run_ids, out, None if args.split == "all" else args.split)
        print(path.read_text())
        print(f"\nwritten to {path}")
    elif args.cmd == "aa":
        from slab.harness.report import aa_test

        t = aa_test(args.run_a, args.run_b, args.arm)
        if t is None:
            raise SystemExit("no overlapping results")
        print(f"A/A arm {args.arm}: n={t.n} diff={100 * t.diff:+.1f}pp "
              f"CI[{100 * t.ci_low:+.1f}, {100 * t.ci_high:+.1f}] discordant={t.x_only}/{t.y_only} p={t.p_value:.3f}")
        sys.exit(1 if t.p_value < 0.05 else 0)


if __name__ == "__main__":
    main()
