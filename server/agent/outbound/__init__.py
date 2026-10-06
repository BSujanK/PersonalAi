"""WRITE tools whose effect leaves the owner's accounts: sending mail, uploading, sharing.

Each one resolves its arguments into a pinned payload (exact recipients with NEW/EXTERNAL flags,
attachment names, sizes and checksums, link scope) before the action is stored, so the approval
preview shows everything that will leave and the executor sends exactly that.
"""
