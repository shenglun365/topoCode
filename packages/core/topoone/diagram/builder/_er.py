from typing import Any

from ._segments import header_segment, title_segment, comment_segment


_REL_SYMS = {
    "one_to_one": "||--||",
    "one_to_many": "||--|{",
    "many_to_one": "}|--||",
    "many_to_many": "}|--|{",
    "zero_to_one": "|o--||",
    "zero_to_many": "|o--|{",
}


def build_er(ir: dict) -> str:
    segments: list[str] = []
    segments += header_segment("er")
    segments += title_segment(ir.get("title", ""))
    segments += comment_segment(ir.get("comments"))

    for ent in ir.get("entities", []):
        name = ent.get("name", "")
        attrs = ent.get("attributes") or []
        if attrs:
            segments.append(f'    {name} {{')
            for a in attrs:
                atype = a.get("type", "")
                aname = a.get("name", "")
                pk = a.get("pk", False)
                fk = a.get("fk", False)
                prefix = ""
                if pk:
                    prefix = "* "
                elif fk:
                    prefix = "+ "
                line = f"{prefix}{aname} {atype}".strip()
                segments.append(f"        {line}")
            segments.append("    }")
        else:
            segments.append(f"    {name}")

    for rel in ir.get("relations", []):
        frm = rel.get("from", "")
        to = rel.get("to", "")
        rtype = rel.get("type", "one_to_many")
        label = rel.get("label", "")
        sym = _REL_SYMS.get(rtype, "||--|{")
        if label:
            segments.append(f"    {frm} {sym} {to} : {label}")
        else:
            segments.append(f"    {frm} {sym} {to}")

    return "\n".join(segments)
