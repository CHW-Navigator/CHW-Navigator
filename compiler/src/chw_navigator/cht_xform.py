from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .form_ir import SurveyRow
from .xlsform_backend import BuiltXLSForm


XFORMS = "http://www.w3.org/2002/xforms"
XHTML = "http://www.w3.org/1999/xhtml"
JR = "http://openrosa.org/javarosa"
CHT = "https://communityhealthtoolkit.org"

ET.register_namespace("h", XHTML)
ET.register_namespace("jr", JR)
ET.register_namespace("cht", CHT)
ET.register_namespace("", XFORMS)

_REF = re.compile(r"\$\{([^}]+)\}")


def generate_cht_xform(built: BuiltXLSForm) -> str:
    """Render the compiler's supported survey-row subset as an executable CHT XForm."""

    workbook = built.workbook
    html = ET.Element(f"{{{XHTML}}}html", {"xmlns:cht": CHT})
    head = ET.SubElement(html, f"{{{XHTML}}}head")
    ET.SubElement(head, f"{{{XHTML}}}title").text = workbook.title
    model = ET.SubElement(head, f"{{{XFORMS}}}model")
    instance = ET.SubElement(model, f"{{{XFORMS}}}instance")
    data = ET.SubElement(instance, "data", {"id": workbook.form_id})

    row_paths: list[tuple[SurveyRow, str]] = []
    name_paths: dict[str, str] = {}
    element_stack: list[tuple[ET.Element, str]] = [(data, "/data")]
    for row in workbook.survey:
        if row.type in {"begin group", "begin_group"}:
            parent, parent_path = element_stack[-1]
            element = ET.SubElement(parent, row.name)
            path = f"{parent_path}/{row.name}"
            row_paths.append((row, path))
            element_stack.append((element, path))
            continue
        if row.type in {"end group", "end_group"}:
            if len(element_stack) == 1:
                raise ValueError("CHT XForm generation found an unmatched end group")
            row_paths.append((row, element_stack[-1][1]))
            element_stack.pop()
            continue
        parent, parent_path = element_stack[-1]
        ET.SubElement(parent, row.name)
        path = f"{parent_path}/{row.name}"
        if row.name in name_paths:
            raise ValueError(f"CHT XForm generation requires globally unique row names; found '{row.name}'")
        name_paths[row.name] = path
        row_paths.append((row, path))
    if len(element_stack) != 1:
        raise ValueError("CHT XForm generation found an unclosed group")
    meta = ET.SubElement(data, "meta", {"tag": "hidden"})
    ET.SubElement(meta, "instanceID")

    ET.SubElement(model, f"{{{XFORMS}}}instance", {"id": "contact-summary"})
    ET.SubElement(model, f"{{{XFORMS}}}instance", {"id": "user-contact-summary"})
    for list_name in sorted({choice.list_name for choice in workbook.choices}):
        choice_instance = ET.SubElement(model, f"{{{XFORMS}}}instance", {"id": list_name})
        root = ET.SubElement(choice_instance, "root")
        for choice in workbook.choices:
            if choice.list_name != list_name:
                continue
            item = ET.SubElement(root, "item")
            ET.SubElement(item, "name").text = choice.name
            ET.SubElement(item, "label").text = choice.label

    for row, path in row_paths:
        if row.type in {"end group", "end_group"}:
            continue
        attributes = {"nodeset": path}
        if row.type not in {"begin group", "begin_group"}:
            attributes["type"] = row.bind_type or _xform_type(row.type)
        if row.calculation:
            attributes["calculate"] = _absolute_refs(row.calculation, name_paths)
        if row.relevant:
            attributes["relevant"] = _absolute_refs(row.relevant, name_paths)
        if row.required:
            attributes["required"] = "true()" if row.required == "yes" else _absolute_refs(row.required, name_paths)
        if row.constraint:
            attributes["constraint"] = _absolute_refs(row.constraint, name_paths)
        if row.type == "note":
            attributes["readonly"] = "true()"
        ET.SubElement(model, f"{{{XFORMS}}}bind", attributes)
    ET.SubElement(
        model,
        f"{{{XFORMS}}}bind",
        {
            "nodeset": "/data/meta/instanceID",
            "type": "string",
            "readonly": "true()",
            f"{{{JR}}}preload": "uid",
        },
    )

    body = ET.SubElement(html, f"{{{XHTML}}}body")
    body_stack: list[ET.Element] = [body]
    for row, path in row_paths:
        if row.type in {"begin group", "begin_group"}:
            attrs = {"ref": path}
            if row.appearance:
                attrs["appearance"] = row.appearance
            group = ET.SubElement(body_stack[-1], f"{{{XFORMS}}}group", attrs)
            ET.SubElement(group, f"{{{XFORMS}}}label").text = row.label or "NO_LABEL"
            body_stack.append(group)
            continue
        if row.type in {"end group", "end_group"}:
            body_stack.pop()
            continue
        if row.type in {"calculate", "hidden"}:
            continue
        if row.type == "note":
            control = ET.SubElement(body_stack[-1], f"{{{XFORMS}}}input", {"ref": path})
            ET.SubElement(control, f"{{{XFORMS}}}label").text = row.label
            continue
        if row.type.startswith("select_one "):
            list_name = row.type.split(" ", 1)[1]
            control = ET.SubElement(body_stack[-1], f"{{{XFORMS}}}select1", {"ref": path})
            ET.SubElement(control, f"{{{XFORMS}}}label").text = row.label
            itemset = ET.SubElement(
                control,
                f"{{{XFORMS}}}itemset",
                {"nodeset": f"instance('{list_name}')/root/item"},
            )
            ET.SubElement(itemset, f"{{{XFORMS}}}value", {"ref": "name"})
            ET.SubElement(itemset, f"{{{XFORMS}}}label", {"ref": "label"})
            continue
        attrs = {"ref": path}
        if row.appearance:
            attrs["appearance"] = row.appearance
        control = ET.SubElement(body_stack[-1], f"{{{XFORMS}}}input", attrs)
        ET.SubElement(control, f"{{{XFORMS}}}label").text = row.label

    ET.indent(html, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(html, encoding="unicode") + "\n"


def _absolute_refs(expression: str, name_paths: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return name_paths[name]
        except KeyError as exc:
            raise ValueError(f"CHT XForm expression references unknown row '{name}'") from exc

    return _REF.sub(replace, expression)


def _xform_type(row_type: str) -> str:
    if row_type == "integer":
        return "int"
    if row_type == "decimal":
        return "decimal"
    if row_type in {"text", "string", "hidden", "note", "calculate"}:
        return "string"
    if row_type.startswith("select_one "):
        return "string"
    raise ValueError(f"CHT XForm generation does not support survey type '{row_type}'")
