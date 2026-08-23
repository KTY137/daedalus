"""Same-module definition -- no import to follow at all."""


class Cam:
    pass


def uses_local(a: Cam) -> Cam:
    return a
