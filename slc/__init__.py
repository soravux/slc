import logging
import time
import threading
import struct
import socket
import socketserver
from collections import defaultdict


class ConnectionError(Exception):
    pass


def initLogging(stream=None):
    """Initialize the logger. Thanks to snakemq."""
    logger = logging.getLogger("slc")
    logger.setLevel(logging.CRITICAL)
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True   # Kills threads on ctrl-c

    def __init__(self, parent_socket, *args, **kwargs):
        self.parent_socket = parent_socket
        super().__init__(*args, **kwargs)


class SocketserverHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.server.parent_socket.data_to_send[self]
        self.request.setblocking(0)
        self.server.parent_socket.sockets[self] = self.request

    def handle(self):
        while not self.server.shutdown_requested_why_is_this_variable_mangled_by_default:
            if self.server.parent_socket.data_to_send[self]:
                self.server.parent_socket.lock.acquire()
                for data in self.server.parent_socket.data_to_send[self]:
                    self.request.sendall(data)

                self.server.parent_socket.data_to_send[self] = []
                self.server.parent_socket.lock.release()

            self.server.parent_socket.lock.acquire()
            try:
                self.server.parent_socket.data_received[self].extend(self.request.recv(4096))
            except socket.error:
                pass
            self.server.parent_socket.lock.release()

            time.sleep(self.server.parent_socket.poll_delay)

    def finish(self):
        self.server.parent_socket.data_to_send.pop(self)


class Socket:
    def __init__(self, type_="tcp"):
        """Builds a new SLC socket."""
        self.type_ = type_
        self.thread = None
        self.lock = threading.Lock()
        self.state = None
        self.buffer = 4096
        self.sockets = {}
        self.server = None
        self.logger = logging.getLogger("slc")
        self.poll_delay = 0.1
        self.data_to_send = defaultdict(list)
        self.data_received = defaultdict(bytearray)
        self.target_addresses = []
        self.source_addresses = []

    def connect(self, port, address='127.0.0.1', source_address=None):
        """Act as a client"""
        self.state = "client"
        self.target_addresses.append((address, port))
        self.source_addresses.append(source_address)

        self.data_to_send[(address, port)] = []

        self.thread = threading.Thread(target=self._clientHandle)
        self.thread.daemon = True
        self.thread.start()

    def listen(self, port, address='0.0.0.0'):
        """Act as a server"""
        self._cleanup()
        self.state = 'server'

        self.server = ThreadedTCPServer(
            self,
            (address, port),
            SocketserverHandler,
        )
        self.server.allow_reuse_address = True
        self.server.shutdown_requested_why_is_this_variable_mangled_by_default = False
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def send(self, data, target=None):
        """Send data to the peer.
        TODO: Can send any kind of data"""
        if self.state == 'client':
            assert target is not None, "Target must be set if socket is client."
        self.lock.acquire()
        data_size = struct.pack('!I', len(data))
        for key in self.data_to_send.keys():
            self.data_to_send[key].append(data_size + data)
        self.lock.release()

    def receive(self, blocking=True):
        """Receive data from the peer."""
        data_to_return = None
        while True:
            self.lock.acquire()
            for target, _ in self.sockets.items():
                try:
                    data_size = struct.unpack('!I', self.data_received[target][:4])[0]
                except struct.error:
                    continue
                if len(self.data_received[target]) - 4 >= data_size:
                    data_to_return = self.data_received[target][4:data_size + 4]
                    self.data_received[target] = self.data_received[target][data_size + 4:]
                    break
            else:
                self.lock.release()
                time.sleep(self.poll_delay)
                continue
            self.lock.release()
            break
            
        return data_to_return

    def _clientHandle(self):
        """TODO: one socket per thread to prevent create_connection delays."""
        while self.state == 'client':
            for idx, target in enumerate(self.target_addresses):
                if not target in self.sockets:
                    self.sockets[target] = socket.create_connection(target,
                                                                    timeout=10,
                                                                    source_address=self.source_addresses[idx])
                    self.sockets[target].setblocking(0)

            # TODO: Delete one by one to increase performance on large amount of data?
            for target, socket_ in self.sockets.items():
                if self.data_to_send:
                    self.lock.acquire()
                    for data in self.data_to_send[target]:
                        socket_.sendall(data)

                    self.data_to_send[target][:] = []
                    self.lock.release()

                self.lock.acquire()
                try:
                    self.data_received[target].extend(socket_.recv(4096))
                except socket.error:
                    pass
                finally:
                    self.lock.release()

            time.sleep(self.poll_delay)

    def _cleanup(self):
        self.state = None

        if self.server:
            self.server.shutdown_requested_why_is_this_variable_mangled_by_default = True
            self.server.shutdown()

        if self.thread and self.thread.is_alive():
            self.thread.join()
