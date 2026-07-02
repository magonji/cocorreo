"""Streaming parser for mbox files.

Iterates over messages without loading the whole file into memory. Suitable
for 20+ GB files that don't fit in RAM.

Algorithm (mbox-O, the one Thunderbird uses):
    Each message starts with a 'From ' line at column 0, followed by the
    RFC 5322 block (headers + body). The next 'From ' at column 0
    marks the end of the previous message. Within the body, lines starting
    with 'From ' are escaped to '>From ' when the mbox is written.

Limitations:
    We don't undo the '>From ' → 'From ' escaping when returning bytes. The
    MIME parser isn't affected because the line is still part of the body.
    If the mbox is the RD variant (no escaping), a body with 'From '
    at the start of a line will cause an incorrect split. We accept this: the
    importer will record the affected message in `import_runs.notes`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

FROM_PREFIX = b"From "


def iter_messages(path: Path) -> Iterator[tuple[int, bytes]]:
    """Yields `(offset_of_the_From_line, message_bytes_without_From_line)` per message.

    The returned bytes do NOT include the separating 'From ' line — they are
    the raw RFC 5322 bytes, ready to hand to the email parser.
    """
    with path.open("rb") as f:
        # Locate the first 'From ' line. Some files may have leading
        # junk; we skip ahead until we find the first separator.
        msg_offset = -1
        offset = 0
        first_line = f.readline()
        if not first_line:
            return  # empty file
        if first_line.startswith(FROM_PREFIX):
            msg_offset = 0
            offset = len(first_line)
        else:
            # Look for the first 'From '
            offset = len(first_line)
            while True:
                line = f.readline()
                if not line:
                    return
                if line.startswith(FROM_PREFIX):
                    msg_offset = offset
                    offset += len(line)
                    break
                offset += len(line)

        # From here on, we accumulate the message body in a buffer.
        # When we see another 'From ' at column 0, we yield it.
        buffer = bytearray()
        while True:
            line = f.readline()
            if not line:
                if buffer:
                    yield msg_offset, bytes(buffer)
                return
            if line.startswith(FROM_PREFIX):
                yield msg_offset, bytes(buffer)
                buffer.clear()
                msg_offset = offset
                offset += len(line)
            else:
                buffer.extend(line)
                offset += len(line)
