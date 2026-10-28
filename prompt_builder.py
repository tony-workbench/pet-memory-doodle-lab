"""Build the doodle prompt from the v2 reference template."""

from pathlib import Path


DEFAULT_SCENE = (
    "a stick figure walks a small four-legged dog through a park as the dog chases "
    "two tumbling leaves, tugging its leash; the person leans forward with one arm outstretched"
)
DEFAULT_OBJECTS = "the stick figure, the small four-legged dog, the leash, and two falling leaves"
LIMITS = {"scene": 600, "objects": 300}
REFERENCE_PATH = Path(__file__).resolve().parent / "prompts" / "reference-v2.txt"


class InputError(ValueError):
    """A safe, user-facing validation message."""


def validate_input(payload):
    if not isinstance(payload, dict):
        raise InputError("Send a JSON object with scene and objects fields.")
    if any(key not in LIMITS for key in payload):
        raise InputError("Only scene and objects fields are accepted.")
    values = {}
    defaults = {"scene": DEFAULT_SCENE, "objects": DEFAULT_OBJECTS}
    for key, limit in LIMITS.items():
        value = payload.get(key, defaults[key])
        if not isinstance(value, str):
            raise InputError("The %s field must be text." % key)
        value = value.strip()
        if not value:
            raise InputError("The %s field cannot be empty." % key)
        if len(value) > limit:
            raise InputError("The %s field must contain at most %d characters." % (key, limit))
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value):
            raise InputError("The %s field contains unsupported control characters." % key)
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise InputError("The %s field contains invalid Unicode characters." % key)
        values[key] = value
    return values


def build_prompt(payload=None):
    values = validate_input({} if payload is None else payload)
    reference = REFERENCE_PATH.read_text(encoding="utf-8")
    # Replace the reference spans in a single pass so user text containing either
    # default phrase is never treated as another template placeholder.
    scene_start = reference.find(DEFAULT_SCENE)
    objects_start = reference.find(DEFAULT_OBJECTS)
    if (scene_start < 0 or objects_start < scene_start + len(DEFAULT_SCENE)
            or reference.count(DEFAULT_SCENE) != 1 or reference.count(DEFAULT_OBJECTS) != 1):
        raise RuntimeError("The local prompt reference needs repair.")
    suffix = reference[objects_start + len(DEFAULT_OBJECTS):]
    if values != {"scene": DEFAULT_SCENE, "objects": DEFAULT_OBJECTS}:
        suffix = suffix.replace(
            "The dog is a very simple animal outline with four legs and tiny dot eyes.",
            "Any pet in the scene is a very simple animal outline with four legs and tiny dot eyes.",
            1,
        )
    return (
        reference[:scene_start] + values["scene"]
        + reference[scene_start + len(DEFAULT_SCENE):objects_start] + values["objects"]
        + suffix
    )
