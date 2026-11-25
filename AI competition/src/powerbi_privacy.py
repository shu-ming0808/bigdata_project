"""Display-only masking; not irreversible anonymization or a change of identity keys."""

def mask_teacher_name(name):
    name = str(name or "").strip()
    if not name:
        return ""
    if len(name) == 1:
        return "O"
    if len(name) == 2:
        return name[0] + "O"
    return name[0] + "O" * (len(name) - 2) + name[-1]
