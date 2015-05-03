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

from . import security, minusconf


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


def _print_discovery_error(seeker, opposite, error_str):
    sys.stderr.write("Error from {opposite}: {error_str}\n".format(
        opposite=opposite,
        error_str=error_str,
    ))


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True   # Kills threads on ctrl-c
    allow_reuse_address = True

    def __init__(self, parent_socket, *args, **kwargs):
        self.parent_socket = parent_socket
        super().__init__(*args, **kwargs)


class SocketserverHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.server.parent_socket.target_addresses.append(self.client_address)
        self.server.parent_socket.data_to_send[self.client_address] = [struct.pack('!IHB', 0, self.server.parent_socket.send_msg_idx[self.client_address], self.server.parent_socket.config)]
        self.request.setblocking(0)
        self.server.parent_socket.sockets[self.client_address] = self.request
        self.server.parent_socket.send_msg_idx[self.client_address] = 2

        if self.server.parent_socket.secure:
            our_key = pickle.dumps(security.getOurPublicKey())
            data_size = struct.pack('!IH', len(our_key), self.server.parent_socket.recv_msg_idx[self.client_address])
            self.server.parent_socket.data_to_send[self.client_address].append(data_size + our_key)
            self.server.parent_socket.send_msg_idx[self.client_address] = 3

        self.header_received = False

    def handle(self):
        while not self.server.shutdown_requested_why_is_this_variable_mangled_by_default:
            if self.server.parent_socket.data_to_send[self.client_address]:
                self.server.parent_socket.lock.acquire()
                for data in self.server.parent_socket.data_to_send[self.client_address]:
                    self.request.sendall(data)

                self.server.parent_socket.data_awaiting[self.client_address].extend(self.server.parent_socket.data_to_send[self.client_address])
                self.server.parent_socket.data_to_send[self.client_address][:] = []
                self.server.parent_socket.lock.release()

            self.server.parent_socket.lock.acquire()
            try:
                self.server.parent_socket.data_received[self.client_address].extend(self.request.recv(4096))
            except socket.error:
                pass

            if not self.header_received:
                self.header_received = self.server.parent_socket.receive(source=self.client_address, timeout=0, _locks=False)

            if self.server.parent_socket.secure and not self.client_address in self.server.parent_socket.crypto_boxes:
                source_key = self.server.parent_socket.receive(source=self.client_address, timeout=0, _locks=False)
                if source_key:
                    self.server.parent_socket.crypto_boxes[self.client_address] = security.getBox(source_key, self.client_address)
            self.server.parent_socket.lock.release()

            time.sleep(self.server.parent_socket.poll_delay) # Replace by select

    def finish(self):
        try:
            self.server.parent_socket.data_to_send.pop(self)
        except KeyError:
            pass
        try:
            self.server.parent_socket.target_addresses.remove(self.client_address)
        except ValueError:
            pass


class Socket:
    def __init__(self, secure=False, compress=False, type_="tcp"):
        """Builds a new SLC socket."""
        self.type_ = type_
        self.client_thread = None
        self.server_threads = []
        self.lock = threading.Lock()
        self.state = set()
        self.buffer = 4096
        self.sockets = {}
        self.client_header_received = defaultdict(bool)
        self.sockets_config = defaultdict(int)
        self.send_msg_idx = defaultdict(int)
        self.recv_msg_idx = defaultdict(int)
        self.servers = []
        self.poll_delay = 0.1
        self.data_to_send = defaultdict(list)
        self.data_awaiting = defaultdict(list)
        self.data_received = defaultdict(bytearray)
        self.target_addresses = []
        self.source_addresses = []
        self.port = None
        self.secure = secure * SOCKET_CONFIG.ENCRYPTED
        self.compressed = compress * SOCKET_CONFIG.COMPRESSED
        self.config = self.secure | self.compressed

        if self.secure:
            self.crypto_boxes = {}

    def connect(self, port, address='127.0.0.1', timeout=None, source_address=None):
        """Act as a client"""
        ts_begin = time.time()

        self.state |= set(("client",))
        self.target_addresses.append((address, port))
        self.source_addresses.append(source_address)
        target = (address, port)

        # Send configuration
        self.data_to_send[target] = []

        if not self.client_thread:
            self.client_thread = threading.Thread(target=self._clientHandle)
            self.client_thread.daemon = True
            self.client_thread.start()


        is_not_ready = lambda: not self.client_header_received[target] or (
            self.secure and not target in self.crypto_boxes
        )
        while is_not_ready():
            if timeout is not None and time.time() - ts_begin > timeout:
                break
            time.sleep(0.1) # Replace by select

    def listen(self, port=0, address='0.0.0.0'):
        """Act as a server"""
        self.state |= set(('server',))

        if self.secure:
            security.initializeSecurity()

        self.servers.append(ThreadedTCPServer(
            self,
            (address, port),
            SocketserverHandler,
        ))
        self.servers[-1].shutdown_requested_why_is_this_variable_mangled_by_default = False
        self.server_threads.append(threading.Thread(target=self.servers[-1].serve_forever))
        self.server_threads[-1].daemon = True
        self.server_threads[-1].start()

        self.port = self.servers[-1].socket.getsockname()[1]

    def advertise(self, stype, sname, advertisername, location=""):
        """Advertise the current server on the network"""
        # TODO: ports can be comma separated
        assert 'server' in self.state
        service = minusconf.Service(stype, self.port, sname, location)
        advertiser = minusconf.ThreadAdvertiser([service], advertisername)
        advertiser.start()
        return advertiser

    def discover(self, stype, sname, advertisername=""):
        se = minusconf.Seeker(stype=stype, aname=advertisername, sname=sname,
                              error_callback=_print_discovery_error)
        se.run()
        return se.results

    def _prepareData(self, data, target):
        # TODO: Use messagepack, fallback on pickle
        # TODO: pickle.HIGHEST_PROTOCOL gives a pretty large output.
        stream = pickle.dumps(data, pickle.HIGHEST_PROTOCOL)
        if self.sockets_config[target] & SOCKET_CONFIG.COMPRESSED:
            stream = zlib.compress(stream)
        if self.sockets_config[target] & SOCKET_CONFIG.ENCRYPTED:
            stream = self.crypto_boxes[target].encrypt(stream)
        return stream

    def send(self, data, target=None):
        """Send data to the peer."""
        if target is None:
            targets = self.data_to_send.keys()
        # TODO: Improve this condition to check if source is a list of targets
        elif '__iter__' in dir(target) and type(target[0]) is tuple:
            targets = target
        else:
            targets = [target]

        for t in targets:
            if t not in self.target_addresses:
                logger = logging.getLogger("slc")
                logger.error("Target unknown: {}.".format(t))
                raise Exception("Unknown source")

        for t in targets:
            data_serialized = self._prepareData(data, t)
            data_header = struct.pack('!IH', len(data_serialized), self.send_msg_idx[t])
            self.lock.acquire()
            self.send_msg_idx[t] += 1
            self.data_to_send[t].append(data_header + data_serialized)
            self.lock.release()

    def receive(self, source=None, timeout=None, _locks=True):
        """Receive data from the peer."""
        ts_begin = time.time()
        data_to_return = None
        config_size = 6
        config_header_size = config_size + 1

        if source is None:
            targets = self.data_received.keys()
        # TODO: Improve this condition to check if source is a list of targets
        elif '__iter__' in dir(source) and type(source[0]) is tuple:
            targets = source
        else:
            targets = [source]

        for target in targets:
            if target not in self.target_addresses:
                logger = logging.getLogger("slc")
                logger.error("Target unknown: {}.".format(target))
                raise Exception("Unknown source")

        while True:
            if _locks:
                self.lock.acquire()
            for target in targets:
                send_idx = self.send_msg_idx[target]
                len_sent = len(self.data_to_send[target])
                len_buffer = len(self.data_awaiting[target])

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
                    # Send missed packets
                    data_waiting_begin = (send_idx - len_sent - len_buffer) - msg_idx
                    del self.data_awaiting[target][:data_waiting_begin]
                    for x in self.data_awaiting[target]:
                        pass
                        #self.send(x, target=target)

                    if _locks:
                        self.lock.release()
                    return True # Move that and the previous if elsewhere?
                elif data_size == 1:
                    assert send_idx - len_sent - len_buffer - 1 == msg_idx
                    try:
                        self.data_awaiting[target].pop(0)
                    except IndexError:
                        # It is the public encryption key (not in data_awaiting)
                        pass
                    self.data_received[target] = self.data_received[target][config_size:]
                    continue

                elif len(self.data_received[target]) - config_size >= data_size:
                    self.recv_msg_idx[target] = msg_idx
                    data_to_return = self.data_received[target][config_size:data_size + config_size]
                    msg_source = target
                    self.data_received[target] = self.data_received[target][data_size + config_size:]

                    # Send ack packet
                    self.data_to_send[target].append(struct.pack('!IH', 1, msg_idx))
                    break
            else:
                if _locks:
                    self.lock.release()
                time.sleep(self.poll_delay) # TODO: Replace by select

                ts = time.time()
                if timeout == None or ts - ts_begin < timeout:
                    continue
                else:
                    break
            if _locks:
                self.lock.release()
            break

        if data_to_return:
            if self.sockets_config[target] & SOCKET_CONFIG.ENCRYPTED and msg_source in self.crypto_boxes:
                data_to_return = self.crypto_boxes[msg_source].decrypt(bytes(data_to_return))
            if self.sockets_config[target] & SOCKET_CONFIG.COMPRESSED and (not self.secure or msg_source in self.crypto_boxes):
                data_to_return = zlib.decompress(data_to_return)
                
            return pickle.loads(data_to_return)

    def shutdown(self):
        self.state = set()

        sockets_to_clean = list(self.sockets.values())
        for server in self.servers:
            sockets_to_clean.append(server.socket)
            server.shutdown_requested_why_is_this_variable_mangled_by_default = True
            server.shutdown()

        if self.client_thread and self.client_thread.is_alive():
            self.client_thread.join()

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
        while 'client' in self.state:
            for idx, target in enumerate(self.target_addresses):
                if not target in self.sockets:
                    try:
                        self.sockets[target] = socket.create_connection(target,
                                                                        timeout=5,
                                                                        source_address=self.source_addresses[idx])
                    except ConnectionRefusedError as e:
                        logger = logging.getLogger("slc")
                        logger.warning("Could not connect to: {}.\n{}".format(target, e))
                        continue
                    self.sockets[target].setblocking(0)

                    # Send SLC header
                    self.lock.acquire()
                    self.data_to_send[target].insert(0, struct.pack('!IHB', 0, self.send_msg_idx[target], self.config))
                    self.send_msg_idx[target] = 2

                    if self.secure:
                        our_key = pickle.dumps(security.getOurPublicKey())
                        data_size = struct.pack('!IH', len(our_key), self.send_msg_idx[target])
                        self.data_to_send[target].insert(1, data_size + our_key)
                        self.send_msg_idx[target] = 3
                    self.lock.release()

            for target, socket_ in self.sockets.items():
                # Check if socket is still alive
                try:
                    ready_to_read, ready_to_write, in_error = \
                        select.select([socket_,], [socket_,], [], 0)
                except (select.error, ValueError):
                    logger = logging.getLogger("slc")
                    logger.warning("{} disconnected from {}.".format(self.port, target))
                    try:
                        socket_.shutdown(2)    # 0 = done receiving, 1 = done sending, 2 = both
                        socket_.close()
                    except OSError:
                        # Socket was already closed
                        pass
                    self.lock.acquire()
                    self.sockets.pop(target)
                    self.lock.release()
                    break

                if self.data_to_send[target]:
                    self.lock.acquire()
                    for data in self.data_to_send[target]:
                        try:
                            res = socket_.sendall(data)
                        except BrokenPipeError:
                            try:
                                socket_.shutdown(2)    # 0 = done receiving, 1 = done sending, 2 = both
                                socket_.close()
                            except OSError:
                                # Socket was already closed
                                pass
                            break
                    self.data_awaiting[target].extend(self.data_to_send[target])
                    self.data_to_send[target][:] = []
                    self.lock.release()

                self.lock.acquire()
                try:
                    self.data_received[target].extend(socket_.recv(4096))
                except socket.error:
                    pass

                if not self.client_header_received[target]:
                    self.client_header_received[target] = self.receive(source=target, timeout=0, _locks=False)

                if self.secure and not target in self.crypto_boxes:
                    source_key = self.receive(source=target, timeout=0, _locks=False)
                    if source_key:
                        self.crypto_boxes[target] = security.getBox(source_key, target)

                self.lock.release()

            time.sleep(self.poll_delay) # Replace by select
