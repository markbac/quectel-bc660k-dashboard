"""A scriptable stand-in for ``serial.Serial`` used by the tests."""
from typing import Dict, List, Union


class FakeSerial:
    """Replies to AT commands from a table of ``command -> response``.

    A value may be a list, consumed one reply per call with the last one
    repeating. Commands without an entry get ``"\\r\\nOK\\r\\n"``.
    """

    def __init__(self, responses: Dict[str, Union[str, List[str]]]):
        self.responses = responses
        self.is_open = True
        self.sent: List[str] = []
        self._buffer = b""

    def write(self, data: bytes) -> int:
        cmd = data.decode("ascii").strip()
        self.sent.append(cmd)
        reply = self.responses.get(cmd, "\r\nOK\r\n")
        if isinstance(reply, list):
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        self._buffer += reply.encode("ascii")
        return len(data)

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def read(self, size: int = 1) -> bytes:
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def reset_input_buffer(self) -> None:
        self._buffer = b""

    def close(self) -> None:
        self.is_open = False
