from __future__ import annotations


class HandoverError(RuntimeError):
    pass


class HandoverConflictError(HandoverError):
    pass
