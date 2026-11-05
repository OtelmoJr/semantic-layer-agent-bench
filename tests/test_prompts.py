from slab.agent.prompts import BASE, render_glossary, system_prompt


def test_only_arm_b_gets_the_glossary():
    g = render_glossary()
    assert g in system_prompt("B")
    assert g not in system_prompt("A")
    assert g not in system_prompt("C")


def test_arms_share_the_same_base_rules():
    for arm in "ABC":
        p = system_prompt(arm)
        assert "Do not round numbers." in p
        assert "Rates are fractions" in p
    assert system_prompt("A") == system_prompt("B")[: len(system_prompt("A"))]


def test_glossary_mentions_every_metric():
    g = render_glossary()
    for name in ("net_revenue", "return_rate", "average_order_value", "late_line_rate", "net_revenue_yoy_growth"):
        assert f"- {name} (" in g
    assert "{" not in BASE.replace("{submit_tool}", "")
