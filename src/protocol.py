"""XML request validation and response serialization."""

from xml.etree import ElementTree as ET


INTEGER = {
    "key", "datetime", "person", "message", "done", "started",
}
FIELDS = {
    "person": {"key", "datetime", "platform", "user_agent"},
    "message": {"key", "datetime", "data", "person", "tags", "done",
                "started"},
    "feedback": {"key", "datetime", "response", "status", "failure",
                 "message"},
}
CREATE = {
    "person": {"datetime", "platform", "user_agent"},
    "message": {"datetime", "data", "person", "tags"},
}
MAX_BODY = 2 * 1024 * 1024
MIN_INTEGER = -(2 ** 63)
MAX_INTEGER = 2 ** 63 - 1


def as_integer(value):
    """Use the same integer range for both storage engines."""
    result = int(value)
    if not MIN_INTEGER <= result <= MAX_INTEGER:
        raise ValueError("integer outside signed 64-bit range")
    return result


def xml_fields(body, tag, fields):
    """Parse a flat XML document with unique, known field names."""
    if not body:
        raise ValueError("XML body required")
    source = body.decode("utf-8")
    if "<!DOCTYPE" in source:
        raise ValueError("document types are forbidden")
    root = ET.fromstring(source)
    if root.tag != tag or root.attrib or (root.text or "").strip():
        raise ValueError(f"expected <{tag}>")
    result = {}
    for child in root:
        name = child.tag
        if name not in fields or name in result:
            raise ValueError(f"unknown or repeated field: {name}")
        if child.attrib or len(child) or (child.tail or "").strip():
            raise ValueError(f"expected a plain field: {name}")
        value = child.text or ""
        result[name] = as_integer(value) if name in INTEGER else value
    return result


def encode_xml(tag, rows):
    """Encode a record, a collection, or an error as UTF-8 XML."""
    root = ET.Element(tag)
    if isinstance(rows, dict):
        append_fields(root, rows)
    else:
        item_tag, entries = rows
        for row in entries:
            append_fields(ET.SubElement(root, item_tag), row)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def append_fields(node, row):
    for field, value in row.items():
        ET.SubElement(node, field).text = str(value)
