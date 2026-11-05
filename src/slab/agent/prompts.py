"""System prompts. One base prompt for every arm; arm B appends the rendered glossary.

Output-format rules (no rounding, fractions, DATE buckets) are in the base prompt for all
arms, because they are about how the answer is compared, not about business knowledge.
"""

from __future__ import annotations

from functools import lru_cache

import yaml

from slab import config

BASE = """You are a data analyst. Answer one business question about a company's sales data.

How to work:
- Use the tools to explore the data and test your query before answering.
- When you are confident, call {submit_tool} exactly once with your final query. The rows it returns are your answer.
- If the question cannot be answered with the data available to you, call refuse with a short reason instead of guessing.

Answer format:
- Return only the columns needed: the grouping columns plus the requested values.
- Do not round numbers.
- Rates are fractions between 0 and 1, not percentages.
- Time buckets (month, quarter, year, ...) are returned as the DATE that starts the bucket.
- For rankings or top-N, order the rows and limit them as asked.
"""

SUBMIT_TOOL = {"A": "submit_sql", "B": "submit_sql", "C": "submit_metric_query"}


@lru_cache(maxsize=1)
def render_glossary() -> str:
    g = yaml.safe_load(config.GLOSSARY_PATH.read_text())
    lines = ["Business glossary (the company's official definitions):", "", "Conventions:"]
    lines += [f"- {c}" for c in g["conventions"]]
    lines += ["", "Metrics:"]
    for m in g["metrics"]:
        lines.append(f"- {m['name']} ({m['label']}): {m['description']} How to compute: {m['raw_sql']}")
    lines += ["", "Dimensions:"]
    for d in g["dimensions"]:
        lines.append(f"- {d['name']}: {d['description']} Source: {d['raw_sql']}")
    return "\n".join(lines)


def system_prompt(arm: str) -> str:
    prompt = BASE.format(submit_tool=SUBMIT_TOOL[arm])
    if arm == "B":
        prompt += "\n" + render_glossary() + "\n"
    return prompt
