"""Render a claimprov PROV-O graph as a diagram with Graphviz.

    python examples/render_graph.py examples/sample_graph.ttl -o sample_graph.svg

Nodes are shaped by PROV type (Entity = box, Activity = rounded box,
Agent = house) and colored by claimprov class. The declared status is
shown inside each Claim; the enacted status inside each Retrieval, and a
Retrieval whose required status outranks the claim's declared status, with
no review, is drawn in red (status inflation).
Requires the `dot` binary (apt install graphviz / brew install graphviz).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from rdflib import RDF, RDFS, Graph, Namespace, URIRef
from rdflib.namespace import PROV

CP = Namespace("https://w3id.org/claimprov#")
RANK = {CP.Asserted: 0, CP.Derived: 0, CP.ToolVerified: 1, CP.HumanVerified: 2}

STYLE = {
    CP.Claim: dict(shape="box", style="filled", fillcolor="#fff2cc", color="#b58900"),
    CP.Evidence: dict(shape="note", style="filled", fillcolor="#e8f4ea", color="#2e7d32"),
    CP.Verification: dict(shape="box", style="rounded,filled", fillcolor="#e3f2fd", color="#1565c0"),
    CP.Retrieval: dict(shape="box", style="rounded,filled", fillcolor="#f3e5f5", color="#6a1b9a"),
    CP.Asset: dict(shape="cylinder", style="filled", fillcolor="#f5f5f5", color="#616161"),
    CP.AcceptancePolicy: dict(shape="component", style="filled", fillcolor="#fafafa", color="#9e9e9e"),
    CP.LLMAgent: dict(shape="house", style="filled", fillcolor="#fbe9e7", color="#bf360c"),
    CP.Tool: dict(shape="house", style="filled", fillcolor="#eceff1", color="#37474f"),
    PROV.Person: dict(shape="house", style="filled", fillcolor="#fff8e1", color="#ff8f00"),
}
EDGES = {
    PROV.wasAttributedTo: "wasAttributedTo",
    PROV.wasDerivedFrom: "wasDerivedFrom",
    PROV.wasAssociatedWith: "wasAssociatedWith",
    PROV.used: "used",
    CP.supportedBy: "supportedBy",
    CP.verifiedBy: "verifiedBy",
    CP.storedIn: "storedIn",
    PROV.hadPlan: "hadPlan",
    PROV.generated: "generated",
}


def local(u: URIRef) -> str:
    s = str(u)
    return s.rsplit("#", 1)[-1] if "#" in s else s.rsplit(":", 1)[-1]


def label_for(g: Graph, n: URIRef, kind: URIRef) -> str:
    name = str(g.value(n, RDFS.label) or local(n))
    if kind == CP.Claim:
        st = g.value(n, CP.declaredStatus)
        rk = g.value(n, CP.recordKind)
        stmt = str(g.value(n, CP.statement) or "")
        if len(stmt) > 38:
            stmt = stmt[:35] + "…"
        kind_s = f" · {local(rk)}" if rk else ""
        return f"{stmt}\\n[declared: {local(st)}{kind_s}]"
    if kind == CP.Retrieval:
        req = g.value(n, CP.requiredStatus)
        use = g.value(n, CP.observedUse)
        rv = g.value(n, CP.reviewed)
        rv_s = " · reviewed" if rv is not None and bool(rv.toPython()) else ""
        return f"Retrieval → {local(use)}\\n[required: {local(req)}{rv_s}]"
    if kind == CP.Asset:
        return f"{name}\\n[default: {local(g.value(n, CP.defaultStatus))}]"
    if kind == CP.Verification:
        return f"Verification\\n{g.value(n, CP.method)} · {local(g.value(n, CP.outcome))}"
    if kind == CP.Evidence:
        return f"Evidence\\n{local(g.value(n, CP.evidenceKind))}"
    return name


def to_dot(g: Graph) -> str:
    lines = [
        "digraph claimprov {",
        '  rankdir=LR; fontname="Helvetica"; node [fontname="Helvetica", fontsize=10]; edge [fontname="Helvetica", fontsize=8, color="#555555"];',
    ]
    kinds: dict[URIRef, URIRef] = {}
    for kind in STYLE:
        for n in g.subjects(RDF.type, kind):
            kinds.setdefault(n, kind)
    for n, kind in kinds.items():
        attrs = dict(STYLE[kind])
        if kind == CP.Retrieval:
            claim = g.value(n, PROV.used)
            d = g.value(claim, CP.declaredStatus) if claim else None
            e = g.value(n, CP.requiredStatus)
            rv = g.value(n, CP.reviewed)
            reviewed = rv is not None and bool(rv.toPython())
            if d is not None and e is not None and RANK[e] > RANK[d] and not reviewed:
                attrs.update(color="#c62828", penwidth="2.5", fillcolor="#ffebee")
        a = ", ".join(f'{k}="{v}"' for k, v in attrs.items())
        lines.append(f'  "{n}" [label="{label_for(g, n, kind)}", {a}];')
    for s, p, o in g:
        if p in EDGES and s in kinds and o in kinds:
            style = "" if p != PROV.wasDerivedFrom else ', style="dashed"'
            lines.append(f'  "{s}" -> "{o}" [label="{EDGES[p]}"{style}];')
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ttl")
    ap.add_argument("-o", "--out", default="graph.svg")
    args = ap.parse_args()
    g = Graph().parse(args.ttl, format="turtle")
    dot = to_dot(g)
    fmt = args.out.rsplit(".", 1)[-1]
    try:
        subprocess.run(["dot", f"-T{fmt}", "-o", args.out], input=dot.encode(), check=True)
    except FileNotFoundError:
        sys.exit("Graphviz `dot` not found; install graphviz or use the .dot output.")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
