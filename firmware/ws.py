"""Minimal WebSocket client (RFC 6455) over a plain socket: text and binary frames plus ping/close handling.

The firmware's frozen `websocket` is only a stream wrapper (no handshake), so the handshake and framing
are done here. Client-to-server frames are masked, as required by the spec.
"""
import os
import socket
import struct
import ubinascii

TEXT, BINARY, CLOSE, PING, PONG = 0x1, 0x2, 0x8, 0x9, 0xA
_RXBUF = 8192  # binary frames up to this size are read into one reusable buffer (no allocation per audio frame)


class WebSocket:
    def __init__(self, host, port, path="/", timeout=30):
        self.host = host
        self.port = port
        self.path = path
        self.timeout = timeout
        self.sock = None
        self._rx = bytearray(_RXBUF)

    def connect(self):
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        s = socket.socket()
        s.settimeout(self.timeout)
        s.connect(addr)
        key = ubinascii.b2a_base64(os.urandom(16)).strip().decode()
        request = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n" % (self.path, self.host, self.port, key))
        s.send(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = s.recv(256)
            if not chunk:
                raise OSError("handshake sem resposta")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise OSError("handshake falhou: " + response.split(b"\r\n", 1)[0].decode())
        self.sock = s

    def _recv_exact(self, n):
        """Read exactly n bytes: into the reusable buffer when they fit (the result is only valid until the next read)."""
        if n <= _RXBUF:
            view = memoryview(self._rx)[:n]
        else:
            view = memoryview(bytearray(n))
        got = 0
        while got < n:
            k = self.sock.readinto(view[got:])
            if not k:
                raise OSError("conexao fechada")
            got += k
        return view

    def _frame(self, opcode, payload):
        n = len(payload)
        out = bytearray([0x80 | opcode])
        if n < 126:
            out.append(0x80 | n)
        elif n < 65536:
            out.append(0x80 | 126)
            out += struct.pack(">H", n)
        else:
            out.append(0x80 | 127)
            out += struct.pack(">Q", n)
        # Client frames must carry the mask bit, but the key may be any value. An all-zero key leaves the payload as
        # is: XOR-ing every byte in Python cost ~20 ms per 4 KB audio frame, more than the time the mic needs to fill it.
        out += b"\0\0\0\0"
        out += payload
        self.sock.sendall(out)

    def send(self, text):
        self._frame(TEXT, text.encode())

    def send_bytes(self, data):
        self._frame(BINARY, data)

    def recv(self):
        """Return the next message: a str for text, a memoryview for binary (valid until the next recv).
        Pings are answered and other control frames ignored."""
        while True:
            head = self._recv_exact(2)
            b0, b1 = head[0], head[1]
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = bytes(self._recv_exact(4)) if b1 & 0x80 else None
            data = self._recv_exact(length)
            if mask:
                data = bytes(data[i] ^ mask[i & 3] for i in range(length))
            if opcode == TEXT:
                return bytes(data).decode()
            if opcode == BINARY:
                return data
            if opcode == PING:
                self._frame(PONG, bytes(data))
            elif opcode == CLOSE:
                raise OSError("servidor fechou")

    def alive(self):
        """False if the server closed the connection while idle (it would only show on the next send, losing the audio)."""
        if not self.sock:
            return False
        try:
            self.sock.setblocking(False)
            try:
                return self.sock.recv(1) is None  # None: nothing waiting. b"" is a closed socket; data is unexpected
            except OSError:
                return True  # EAGAIN: nothing waiting, still open
            finally:
                self.sock.settimeout(self.timeout)
        except OSError:
            return False

    def close(self):
        if self.sock:
            try:
                self._frame(CLOSE, b"")
            except OSError:
                pass
            self.sock.close()
            self.sock = None
