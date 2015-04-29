import logging
import select
import os
import sys
import time
import threading
import struct
import socket
import socketserver
import pickle
import zlib
from collections import defaultdict

from . import security


def initLogging(stream=None):
    """Initialize the logger. Thanks to snakemq."""
    logger = logging.getLogger("slc")
    logger.setLevel(logging.WARNING)
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

initLogging()


class SOCKET_CONFIG:
    NORMAL = 0b00000000
    ENCRYPTED = 0b00000001
    COMPRESSED = 0b00000010


class ConnectionError(Exception):
    pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True   # Kills threads on ctrl-c
    allow_reuse_address = True

    def __init__(self, parent_socket, *args, **kwargs):
        self.parent_socket = parent_socket
        super().__init__(*args, **kwargs)


class SocketserverHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.server.parent_socket.data_to_send[self.client_address] = [struct.pack('!IHB', 0, self.server.parent_socket.send_msg_idx[self.client_address], self.server.parent_socket.config)]
        self.request.setblocking(0)
        self.server.parent_socket.sockets[self.client_address] = self.request

        if self.server.parent_socket.secure:
            our_key = pickle.dumps(security.getOurPublicKey())
            data_size = struct.pack('!IH', len(our_key), self.server.parent_socket.recv_msg_idx[self.client_address])
            self.server.parent_socket.data_to_send[self.client_address].append(data_size + our_key)

        self.header_received = False

    def handle(self):
        while not self.server.shutdown_requested_why_is_this_variable_mangled_by_default:
            if self.server.parent_socket.data_to_send[self.client_address]:
                self.server.parent_socket.lock.acquire()
                for data in self.server.parent_socket.data_to_send[self.client_address]:
                    self.request.sendall(data)

                self.server.parent_socket.data_to_send[self.client_address] = []
                self.server.parent_socket.lock.release()

            self.server.parent_socket.lock.acquire()
            try:
                self.server.parent_socket.data_received[self.client_address].extend(self.request.recv(4096))
            except socket.error:
                pass

            if not self.header_received:
                self.header_received = self.server.parent_socket.receive(source=self.client_address, blocking=False, _locks=False)

            if self.server.parent_socket.secure and not self.client_address in self.server.parent_socket.crypto_boxes:
                source_key = self.server.parent_socket.receive(source=self.client_address, blocking=False, _locks=False)
                if source_key:
                    self.server.parent_socket.crypto_boxes[self.client_address] = security.getBox(source_key, self.client_address)
            self.server.parent_socket.lock.release()

            time.sleep(self.server.parent_socket.poll_delay) # Replace by select

    def finish(self):
        try:
            self.server.parent_socket.data_to_send.pop(self)
        except KeyError:
            pass


class Socket:
    def __init__(self, secure=False, compressed=False, type_="tcp"):
        """Builds a new SLC socket."""
        self.type_ = type_
        self.thread = None
        self.lock = threading.Lock()
        self.state = None
        self.buffer = 4096
        self.sockets = {}
        self.sockets_config = defaultdict(int)
        self.send_msg_idx = defaultdict(int)
        self.recv_msg_idx = defaultdict(int)
        self.server = None
        self.poll_delay = 0.1
        self.data_to_send = defaultdict(list)
        self.data_received = defaultdict(bytearray)
        self.target_addresses = []
        self.source_addresses = []
        self.port = None
        self.secure = secure * SOCKET_CONFIG.ENCRYPTED
        self.compressed = compressed * SOCKET_CONFIG.COMPRESSED
        self.config = self.secure | self.compressed

        if self.secure:
            self.crypto_boxes = {}

    def connect(self, port, timeout=-1, address='127.0.0.1', source_address=None):
        """Act as a client"""
        self.state = "client"
        self.target_addresses.append((address, port))
        self.source_addresses.append(source_address)
        target = (address, port)

        # Send configuration
        self.data_to_send[target] = []

        self.thread = threading.Thread(target=self._clientHandle)
        self.thread.daemon = True
        self.thread.start()

        if timeout == -1:
            self.receive(source=target) # Get the header
            if self.secure:
                remote_key = self.receive(source=target) # Get the remote key
                self.crypto_boxes[target] = security.getBox(remote_key, target)
        else:
            raise NotImplementedError("Asynchronous connection feature to come...")

    def listen(self, port=0, address='0.0.0.0'):
        """Act as a server"""
        self.shutdown() # TODO: Needed?
        self.state = 'server'

        if self.secure:
            security.initializeSecurity()

        self.server = ThreadedTCPServer(
            self,
            (address, port),
            SocketserverHandler,
        )
        self.server.shutdown_requested_why_is_this_variable_mangled_by_default = False
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        self.port = self.server.socket.getsockname()[1]

    def _prepareData(self, data, target):
        # TODO: pickle.HIGHEST_PROTOCOL gives a pretty large output.
        stream = pickle.dumps(data, pickle.HIGHEST_PROTOCOL)
        if self.sockets_config[target] & SOCKET_CONFIG.COMPRESSED:
            stream = zlib.compress(stream)
        if self.sockets_config[target] & SOCKET_CONFIG.ENCRYPTED:
            stream = self.crypto_boxes[target].encrypt(stream)
        return stream

    def send(self, data, target=None):
        """Send data to the peer."""
        targets = self.data_to_send.keys() if not target else [target]
        for key in targets:
            data_serialized = self._prepareData(data, key)
            data_header = struct.pack('!IH', len(data_serialized), self.send_msg_idx[key])
            self.lock.acquire()
            self.send_msg_idx[key] += 1
            self.data_to_send[key].append(data_header + data_serialized)
            self.lock.release()

    def receive(self, source=None, blocking=True, _locks=True):
        """Receive data from the peer."""
        data_to_return = None
        config_size = 6
        config_header_size = config_size + 1
        targets = self.data_received.keys() if source is None else [source]
        while True:
            if _locks:
                self.lock.acquire()
            for target in targets:
                try:
                    data_size, msg_idx = struct.unpack('!IH', self.data_received[target][:config_size])[0:2]
                except struct.error as e:
                    continue
                if data_size == 0 and len(self.data_received[target]) >= config_header_size:
                    # data_size == 0 means header
                    preliminary_config = struct.unpack('!B', self.data_received[target][config_size:config_header_size])[0]
                    assert preliminary_config == self.config, "Both sockets must have the same configuration."
                    self.recv_msg_idx[target] = msg_idx
                    self.data_received[target] = self.data_received[target][config_header_size:]
                    self.sockets_config[target] = preliminary_config
                    if _locks:
                        self.lock.release()
                    return True # Move that and the previous if elsewhere?
                elif len(self.data_received[target]) - config_size >= data_size:
                    self.recv_msg_idx[target] = msg_idx
                    data_to_return = self.data_received[target][config_size:data_size + config_size]
                    msg_source = target
                    self.data_received[target] = self.data_received[target][data_size + config_size:]
                    break
            else:
                if _locks:
                    self.lock.release()
                time.sleep(self.poll_delay)
                if blocking:
                    continue
                else:
                    break
            if _locks:
                self.lock.release()
            break

        if data_to_return:
            if self.sockets_config[target] & SOCKET_CONFIG.ENCRYPTED and msg_source in self.crypto_boxes:
                data_to_return = self.crypto_boxes[msg_source].decrypt(bytes(data_to_return))
            if self.sockets_config[target] & SOCKET_CONFIG.COMPRESSED:
                data_to_return = zlib.decompress(data_to_return)
                
            return pickle.loads(data_to_return)

    def shutdown(self):
        self.state = None

        sockets_to_clean = list(self.sockets.values())
        if self.server:
            sockets_to_clean.append(self.server.socket)
            self.server.shutdown_requested_why_is_this_variable_mangled_by_default = True
            self.server.shutdown()

        if self.thread and self.thread.is_alive():
            self.thread.join()

        # TODO: Hum, analyze the impact of this
        for socket_ in sockets_to_clean:
            if socket_._closed:
                continue
            l_onoff = 1
            l_linger = 0
            socket_.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                               struct.pack('hh' if os.name == 'nt' else 'ii', l_onoff, l_linger))
            socket_.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            time.sleep(0.1)
            socket_.close()

    def _clientHandle(self):
        """TODO: one socket per thread to prevent create_connection delays?"""
        while self.state == 'client':
            for idx, target in enumerate(self.target_addresses):
                if not target in self.sockets:
                    self.sockets[target] = socket.create_connection(target,
                                                                    timeout=5,
                                                                    source_address=self.source_addresses[idx])
                    self.sockets[target].setblocking(0)

                    # Send SLC header
                    self.lock.acquire()
                    self.data_to_send[target].insert(0, struct.pack('!IHB', 0, self.send_msg_idx[target], self.config))

                    if self.secure:
                        our_key = pickle.dumps(security.getOurPublicKey())
                        data_size = struct.pack('!IH', len(our_key), self.send_msg_idx[target])
                        self.data_to_send[target].insert(1, data_size + our_key)
                    self.lock.release()

            # TODO: Delete one by one to increase performance on large amount of data?
            for target, socket_ in self.sockets.items():
                # Check if socket is still alive
                try:
                    ready_to_read, ready_to_write, in_error = \
                        select.select([socket_,], [socket_,], [], 0)
                except select.error:
                    socket_.shutdown(2)    # 0 = done receiving, 1 = done sending, 2 = both
                    socket_.close()
                    self.lock.acquire()
                    self.sockets.pop(target)
                    self.lock.release()
                    break

                if self.data_to_send[target]:
                    self.lock.acquire()
                    for data in self.data_to_send[target]:
                        res = socket_.sendall(data)

                    self.data_to_send[target][:] = []
                    self.lock.release()

                self.lock.acquire()
                try:
                    self.data_received[target].extend(socket_.recv(4096))
                except socket.error:
                    pass
                self.lock.release()

            time.sleep(self.poll_delay) # Replace by select
