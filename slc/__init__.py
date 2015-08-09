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
import itertools
from functools import partial
from collections import defaultdict, namedtuple

try:
    import msgpack
except ImportError:
    pass

from . import security, discovery


#######################################
# Logging facilities and initialization
#######################################

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


#######################################
# Constants
#######################################

SERIALIZER = namedtuple("serializer", "protocol, version, dump, load")
"""Namedtuple specifying serialization protocols.

:param protocol: Protocol name.
:param version: Protocol version.
:param dumps: Callable that performs the serialization. Use a `partial` to 
    specify the function arguments.
:param loads: Callable that performs the reverse serialization.
"""

_pickser_highest = partial(pickle.dumps, protocol=pickle.HIGHEST_PROTOCOL)
SER_PICKLE_HIGHEST = SERIALIZER(protocol="pickle", version=pickle.HIGHEST_PROTOCOL,
                                dump=_pickser_highest, load=pickle.loads)
"""Pickle serialization using the highest available protocol."""

_pickser_text = partial(pickle.dumps, protocol=0)
SER_PICKLE_TEXT = SERIALIZER(protocol="pickle", version=0,
                                dump=_pickser_text, load=pickle.loads)
"""Pickle serialization using text-compatible protocol."""

SER_BEST = SER_PICKLE_HIGHEST
"""Best serialization available."""

try:
    _msgpack_ser = partial(msgpack.packb, use_bin_type=True)
    _msgpack_deser = partial(msgpack.unpackb, use_list=False)
    SER_MSGPACK = SERIALIZER(protocol="msgpack", version=msgpack.__version__,
                             dump=_msgpack, load=_msgpack_deser)

    SER_BEST = SER_MSGPACK
except NameError:
    pass

COMPRESSOR = namedtuple("compressor", "name, version, comp, decomp")
"""Namedtuple specifying compressors.

:param name: Compressor name.
:param version: Compressor version.
:param comp: Callable that performs the compression. Use a `partial` to specify
    the function arguments.
:param decomp: Callable that performs the decompression."""


COMP_ZLIB_DEFAULT = COMPRESSOR(name='zlib', version=zlib.ZLIB_VERSION,
                               comp=zlib.compress, decomp=zlib.decompress)
"""zlib compression with default (6) compression level."""


_compress_max = partial(zlib.compress, level=9)

COMP_ZLIB_MAX = COMPRESSOR(name='zlib', version=zlib.ZLIB_VERSION,
                           comp=_compress_max, decomp=zlib.decompress)
"""zlib compression with maximum (9) compression level."""


class SOCKET_CONFIG:
    NORMAL = 0b00000000
    SECURE = 0b00000001
    COMPRESS = 0b00000010


ALL = None
INFINITE = None


#######################################
# Exceptions
#######################################

class ConnectionError(Exception):
    pass


#######################################
# Server related classes
#######################################

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True   # Kills threads on ctrl-c
    allow_reuse_address = True

    def __init__(self, parent_socket, *args, **kwargs):
        self.parent_socket = parent_socket
        super().__init__(*args, **kwargs)


class SocketserverHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.server.parent_socket.lock.acquire()
        self.server.parent_socket.target_addresses.append(self.client_address)
        self.server.parent_socket.data_to_send[self.client_address] = [struct.pack('!B', self.server.parent_socket.config)]
        self.server.parent_socket.data_to_send_id[self.client_address] = [-3]
        self.request.setblocking(0)
        self.server.parent_socket.sockets[self.client_address] = self.request

        if self.server.parent_socket.secure:
            our_key = pickle.dumps(security.getOurPublicKey())
            self.server.parent_socket.data_to_send[self.client_address].append(our_key)
            self.server.parent_socket.data_to_send_id[self.client_address].append(-2)
        self.server.parent_socket.lock.release()

        self.header_received = False

    def handle(self):
        while not self.server.shutdown_requested_why_is_this_variable_mangled_by_default:
            if self.server.parent_socket.data_to_send[self.client_address]:
                to_delete = []
                msg_idx = []
                self.server.parent_socket.lock.acquire()
                for idx, data in enumerate(self.server.parent_socket.data_to_send[self.client_address]):
                    not_header = self.server.parent_socket.data_to_send_id[self.client_address][idx] >= 0
                    if self.server.parent_socket.sockets_config[self.client_address] & SOCKET_CONFIG.SECURE and not_header:
                        try:
                            data = data + self.server.parent_socket.crypto_boxes[self.client_address].encrypt(data)
                        except KeyError:
                            continue
                    
                    if self.server.parent_socket.data_to_send_id[self.client_address][idx] == -3:
                        data_header = struct.pack('!IH', 0, self.server.parent_socket.send_msg_idx[self.client_address])
                        msg_idx.append((0, self.server.parent_socket.send_msg_idx[self.client_address]))
                        self.server.parent_socket.send_msg_idx[self.client_address] += 1
                    elif self.server.parent_socket.data_to_send_id[self.client_address][idx] == -1:
                        data_header = b""
                    else:
                        data_header = struct.pack('!IH', len(data), self.server.parent_socket.send_msg_idx[self.client_address])
                        msg_idx.append((len(data), self.server.parent_socket.send_msg_idx[self.client_address]))
                        self.server.parent_socket.send_msg_idx[self.client_address] += 1
                    
                    if data_header:
                        self.request.sendall(data_header)
                    self.request.sendall(data)
                    
                    to_delete.append(idx)
                for id_idx, idx in enumerate(to_delete):
                    self.server.parent_socket.data_awaiting[self.client_address].append((msg_idx[id_idx], self.server.parent_socket.data_to_send[self.client_address][idx]))
                    self.server.parent_socket.data_awaiting_id[self.client_address].append(self.server.parent_socket.data_to_send_id[self.client_address][idx])
                for idx in reversed(to_delete):
                    self.server.parent_socket.data_to_send[self.client_address].pop(idx)
                    self.server.parent_socket.data_to_send_id[self.client_address].pop(idx)
                self.server.parent_socket.lock.release()

            self.server.parent_socket.lock.acquire()
            try:
                self.server.parent_socket.data_received[self.client_address].extend(self.request.recv(4096))
            except socket.error:
                pass

            if not self.header_received:
                self.header_received = self.server.parent_socket.recv(source=self.client_address, timeout=0, _locks=False)

            if self.server.parent_socket.secure and not self.client_address in self.server.parent_socket.crypto_boxes:
                source_key = self.server.parent_socket.recv(source=self.client_address, timeout=0, _locks=False)
                if source_key:
                    self.server.parent_socket.crypto_boxes[self.client_address] = security.getBox(source_key, self.client_address)
            self.server.parent_socket.lock.release()

            try:
                _, _, _ = select.select([self.request], [], [], self.server.parent_socket.poll_delay)
            except (OSError, ValueError):
                pass

    def finish(self):
        try:
            self.server.parent_socket.data_to_send.pop(self)
            self.server.parent_socket.data_to_send_id.pop(self)
        except KeyError:
            pass
        try:
            self.server.parent_socket.target_addresses.remove(self.client_address)
        except ValueError:
            pass

#######################################


class Communicator:
    """Communicator(self, secure=False, compress=None, serializer=slc.SER_BEST, buffer_cap=slc.INFINITE, timeout=30, retries=INFINITE, protocol="tcp")
        
        Builds a new communicator.

        :param secure: Use encryption and authentication. This makes the
            messages readable only by the target and validates the authenticity
            of the sender.
        :param compress: Compression scheme to use. `None` deactivates
            compression. See slc.COMPRESSOR.
        :param serializer: Namedtuple representing the serialization protocol.
            See slc.SERIALIZER.
        :param buffer_cap: Maximum sending buffer capacity. Past this capacity,
            sending data will block. (*TODO*)
        :param timeout: Timeout in seconds before a connection attempt is
            considered failed.
        :param retries: Number of retries before a socket is considered
            disconnected. After this number of retries, subsequent operations
            on the communicator will raise an exception.
        :param protocol: Underlying protocol to use ('tcp', 'udp', 'icmp'). Only
            'tcp' is supported as of now.
    """
    def __init__(self, secure=False, compress=None, serializer=SER_BEST,
                 buffer_cap=INFINITE, timeout=30, retries=INFINITE,
                 protocol="tcp"):
        self.protocol = protocol
        self.client_thread = None
        self.server_threads = []
        self.lock = threading.Lock()
        self.state = set()
        self.buffer = 4096
        self.sockets = {}
        self.client_header_received = defaultdict(bool)
        self.sockets_config = defaultdict(int)
        self.send_msg_idx = defaultdict(partial(int, 0))
        self.recv_msg_idx = defaultdict(int)
        self.nbr_msg_acked = defaultdict(int)
        self.servers = []
        self.poll_delay = 0.05
        self.data_to_send = defaultdict(list)
        self.data_to_send_id = defaultdict(list)
        self.data_awaiting = defaultdict(list)
        self.data_awaiting_id = defaultdict(list)
        self.data_received = defaultdict(bytearray)
        self.target_addresses = []
        self.source_addresses = []
        self.port = None
        self.serializer = serializer
        self.secure = secure * SOCKET_CONFIG.SECURE
        self.compressed = (compress is not None) * SOCKET_CONFIG.COMPRESS
        self.compress = compress
        self.config = self.secure | self.compressed
        self.receive_cond = threading.Condition()
        self.advertiser = None
        self.advertiser_stop = threading.Event()
        self.next_message_id = 0

        if self.secure:
            self.crypto_boxes = {}

    def connect(self, port, host='127.0.0.1', timeout=INFINITE, source_address=ALL):
        """connect(self, port, host='127.0.0.1', timeout=INFINITE, source_address=ALL)
        Connect to a socket that prealably performed a `listen()`.

        :param port: Target port connect.
        :param host: Target host.
        :param timeout: Maximum time to wait. slc.INFINITE means blocking. 0 means
            non-blocking. Any strictly positive number means to wait for this
            maximum time in seconds to wait. An error is raised in the latter
            case if no data is received.
        :param source_address: Address on which to perform the connection. None
            means all available interfaces.
        """
        ts_begin = time.time()

        self.state |= set(("client",))
        self.target_addresses.append((host, port))
        self.source_addresses.append(source_address)
        target = (host, port)

        # Send configuration
        self.data_to_send[target] = []
        self.data_to_send_id[target] = []

        if not self.client_thread:
            self.client_thread = threading.Thread(target=self._clientHandle)
            self.client_thread.daemon = True
            self.client_thread.start()

        if timeout == 0:
            return

        is_not_ready = lambda: not self.client_header_received[target] or (
            self.secure and not target in self.crypto_boxes
        )
        while is_not_ready():
            if timeout is not None and time.time() - ts_begin > timeout:
                raise ConnectionError('Timeout in connection.')
            self.receive_cond.acquire()
            self.receive_cond.wait(0.1)
            self.receive_cond.release()
            assert self.client_thread.is_alive(), "Client thread terminated unexpectedly."

    def listen(self, port=0, host='0.0.0.0'):
        """Act as a server. Allows other communicators to `connect()` to it.

        :param port: Port on which to listen. Default (0) is to let the operating
            system decide which port, available on the variable `port`.
        :param host: Host address on which to listen to.
        """
        self.state |= set(('server',))

        if self.secure:
            security.initializeSecurity()

        self.servers.append(ThreadedTCPServer(
            self,
            (host, port),
            SocketserverHandler,
        ))
        self.servers[-1].shutdown_requested_why_is_this_variable_mangled_by_default = False
        self.server_threads.append(threading.Thread(target=self.servers[-1].serve_forever))
        self.server_threads[-1].daemon = True
        self.server_threads[-1].start()

        if self.port is None:
            self.port = self.servers[-1].socket.getsockname()[1]
        elif type(self.port) is int:
            self.port = [self.port, self.servers[-1].socket.getsockname()[1]]
        else:
            self.port.append(self.servers[-1].socket.getsockname()[1])

    def advertise(self, name):
        """Advertise the current server on the network.

        *TODO*: Add support for IPv6.

        :param name: Name to advertise."""
        assert 'server' in self.state, "The socket is not listening, nothing to advertise."
        if self.advertiser:
            self.stopAdvertising()

        ports = [str(self.port)] if not hasattr(self.port, '__iter__') \
            else [str(p) for p in self.port]
        self.advertiser_stop.clear()
        self.advertiser = threading.Thread(target=discovery.advertise,
            kwargs={'name': name, 'cond': self.advertiser_stop,
                    'ports': ",".join(ports)})
        self.advertiser.daemon = True
        self.advertiser.start()

    def stopAdvertising(self):
        """Stops advertising the socket."""
        self.advertiser_stop.set()
        self.advertiser.join()
        self.advertiser = None

    def discover(self, name=None):
        """Discover the sockets advertising on the local network.

        :param name: Name to discover. Defaults to discover everything."""
        results = discovery.discover()
        if type(name) is not str and name is not None:
            name = name.decode('utf-8')
        return [r for r in results if name is None or r[0] == name]

    def forward(self, source, target):
        """Move awaiting messages of `source` to `target`."""
        raise NotImplementedError()

    def is_acknowledged(self, message_id, target=ALL):
        """is_acknowledged(self, message_id, target=ALL)
        Returns if the message represented by `message_id` has been
        successfully received by the pair.

        :param message_id: Message ID provided by `send`.
        :param target: Check for a given target or list of targets. If there
            are multiple targets, the function will return true only if all
            targets have acknowledged the message."""
        if target is ALL:
            target = list(self.data_awaiting_id.keys())

        for t in target:
            if message_id in itertools.chain(self.data_awaiting_id[t],
                                             self.data_to_send_id[t]):
                return False
        return True

    def send(self, data, target=ALL, raw=False, _locks=True):
        """send(self, data, target=ALL, raw=False)
        Send data to peer(s).

        :param data: Data to send. Can be any type serializable by the chosen
            serialization protocol if `raw` is `False`. If `raw` is `True`, data
            must have a file-like interface, such as a bytes type.
        :param target: Target peer to send the data to. If `None`, send to
            all peers. If set to a tuple of (host, port), send only to this
            peer. If set to a list of tuples, only send to these particular
            targets.
        :param raw: If the data must be serialized or not before sending.

        :returns: Message ID. Can be used to determine whether or not this 
            message has been acknowledged by all its recipients.
        """
        if target is ALL:
            targets = self.data_to_send.keys()
        elif hasattr(target, '__iter__') and type(target[0]) is tuple:
            targets = target
        else:
            targets = [target]

        for t in targets:
            if t not in self.target_addresses:
                logger = logging.getLogger("slc")
                logger.error("Target unknown: {}.".format(t))
                raise KeyError("Unknown target")

        if not raw:
            data_serialized = self.serializer.dump(data)
        else:
            data_serialized = data

        if self.compressed:
            data_serialized = self.compress.comp(data_serialized)

        for t in targets:
            if _locks:
                self.lock.acquire()
            self.data_to_send[t].append(data_serialized)
            self.data_to_send_id[t].append(self.next_message_id)
            if _locks:
                self.lock.release()
        self.next_message_id += 1
        return self.next_message_id - 1

    def recv(self, source=ALL, timeout=INFINITE, _locks=True):
        """recv(self, source=ALL, timeout=INFINITE)
        Receive data. Same as `receive()`, but won't provide the peer
        address."""
        ret = self.receive(source, timeout, _locks)
        if ret not in [None, False, True]:
            ret = ret[1]
        return ret

    def receive(self, source=ALL, timeout=INFINITE, _locks=True):
        """receive(self, source=ALL, timeout=INFINITE)
        Receive data from the peer.

        :param source: Tuple (host, port) from which to receive from.
        :param timeout: Maximum time to wait. slc.INFINITE means blocking. 0 means
            non-blocking. Any strictly positive number means to wait for this
            maximum time in seconds to wait. An error is raised in the latter
            case if no data is received.

        :returns: src, obj
        """
        global config_size, config_header_size
        ts_begin = time.time()
        data_to_return = None
        config_size = 6
        config_header_size = config_size + 1

        if source is None:
            targets = self.data_received.keys()
        elif hasattr(source, '__iter__') and type(source[0]) is tuple:
            targets = source
        else:
            targets = [source]

        for target in targets:
            if target not in self.target_addresses:
                logger = logging.getLogger("slc")
                logger.error("Target unknown: {}.".format(target))
                raise KeyError("Unknown source")

        while True:
            if _locks:
                self.lock.acquire()
            for target in targets:
                send_idx = self.send_msg_idx[target]
                len_send = len(self.data_to_send[target])
                len_buffer = len(self.data_awaiting[target])

                try:
                    data_size, msg_idx = struct.unpack('!IH', self.data_received[target][:config_size])
                except struct.error as e:
                    continue

                if data_size == 0:
                    if len(self.data_received[target]) < config_header_size:
                        continue
                    # data_size == 0 means header
                    preliminary_config = struct.unpack('!B', self.data_received[target][config_size:config_header_size])[0]
                    assert preliminary_config == self.config, "Both sockets must have the same configuration."
                    self.data_received[target] = self.data_received[target][config_header_size:]
                    self.sockets_config[target] = preliminary_config

                    # Send missed packets during disconnection
                    data_waiting_begin = (send_idx - len_send) - msg_idx
                    del self.data_awaiting[target][:data_waiting_begin]
                    del self.data_awaiting_id[target][:data_waiting_begin]
                    for idx, x in enumerate(self.data_awaiting[target]):
                        # Do not resend header
                        resend_data_size, resend_msg_idx = x[0]
                        if resend_data_size != 0 and (resend_msg_idx > 1 or not self.secure):
                            logger = logging.getLogger("slc")
                            logger.warning('Sending a message again...')
                            self.data_to_send[target].append(x[1])
                            self.data_to_send_id[target].append(self.data_awaiting_id[target][idx])
                    self.data_awaiting[target][:] = []
                    self.data_awaiting_id[target][:] = []

                    if _locks:
                        self.lock.release()
                    self.receive_cond.acquire()
                    self.receive_cond.notify_all()
                    self.receive_cond.release()
                    return True # Move that and the previous if elsewhere?

                elif data_size == 1:
                    # data_size == 1 means ack
                    self.nbr_msg_acked[target] += 1
                    self.data_awaiting[target].pop(0)
                    self.data_awaiting_id[target].pop(0)
                    self.data_received[target] = self.data_received[target][config_size:]
                    continue

                elif len(self.data_received[target]) - config_size >= data_size:
                    if msg_idx <= self.recv_msg_idx[target]:
                        logger = logging.getLogger("slc")
                        logger.warning('Received a message in double.')
                        self.data_received[target] = self.data_received[target][data_size + config_size:]
                        continue
                    self.recv_msg_idx[target] = msg_idx
                    data_to_return = self.data_received[target][config_size:data_size + config_size]
                    msg_source = target
                    self.data_received[target] = self.data_received[target][data_size + config_size:]

                    # Send ack packet
                    self.data_to_send[target].append(struct.pack('!IH', 1, msg_idx))
                    self.data_to_send_id[target].append(-1)
                    break
            else:
                if _locks:
                    self.lock.release()

                try:
                    _, _, _ = select.select(self.sockets.values(), [], [], self.poll_delay)
                except (OSError, ValueError):
                    pass

                if 'client' in self.state:
                    assert self.client_thread, "Client thread could not be launched."
                    assert self.client_thread.is_alive(), "Client thread terminated unexpectedly."
                for thread in self.server_threads:
                    assert thread.is_alive(), "Server thread terminated unexpectedly."

                ts = time.time()
                if timeout == None or ts - ts_begin < timeout:
                    continue
                else:
                    break
            if _locks:
                self.lock.release()
            break

        if data_to_return:
            if self.sockets_config[target] & SOCKET_CONFIG.SECURE and msg_source in self.crypto_boxes:
                data_to_return = self.crypto_boxes[msg_source].decrypt(bytes(data_to_return))
            if self.sockets_config[target] & SOCKET_CONFIG.COMPRESS and (not self.secure or msg_source in self.crypto_boxes):
                data_to_return = self.compress.decomp(data_to_return)
            
            self.receive_cond.acquire()
            self.receive_cond.notify_all()
            self.receive_cond.release()
            return msg_source, self.serializer.load(data_to_return)

        self.receive_cond.acquire()
        self.receive_cond.notify_all()
        self.receive_cond.release()

    def disconnect(self, target=ALL, timeout=INFINITE):
        """disconnect(self, target=ALL, timeout=INFINITE)
        Disconnect target(s) from the communicator.

        :param target: Target to disconnect. slc.ALL means disconnect all
            peers. A tuple (host, port) means to disconnect this particular
            target. A list of tuples disconnects the targets in the list.
        :param timeout: Timeout to ensure all data is sent before disconnecting.
            slc.INFINITE means blocking, 0 means disconnect and discard pending
            messages and any positive number is the maximum time to wait before
            discarding the messages (TODO: Or raising an exception?).
        """
        raise NotImplementedError()

    def shutdown(self):
        """Disconnects every peer and shutdowns the communicator."""
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
        while 'client' in self.state:
            for idx, target in enumerate(self.target_addresses):
                if not target in self.sockets:
                    awaiting_data = tuple(zip(*self.data_awaiting[target]))
                    if len(awaiting_data) > 0:
                        self.data_to_send[target].extend(awaiting_data[1])
                    self.data_to_send_id[target].extend(self.data_awaiting_id[target])
                    self.data_awaiting[target][:] = []
                    self.data_awaiting_id[target][:] = []
                    try:
                        self.sockets[target] = socket.create_connection(target,
                                                                        timeout=5,
                                                                        source_address=self.source_addresses[idx])
                    except Exception as e:
                        logger = logging.getLogger("slc")
                        logger.warning("Could not connect to: {}.\n{}".format(target, e))
                        continue
                    logger = logging.getLogger("slc")
                    logger.info("Established new connection to {}.".format(target))
                    self.sockets[target].setblocking(0)
                    self.client_header_received[target] = False

                    # Send SLC header
                    self.lock.acquire()
                    self.data_to_send[target].insert(0, struct.pack('!B', self.config))
                    self.data_to_send_id[target].insert(0, -3)

                    if self.secure:
                        our_key = pickle.dumps(security.getOurPublicKey())
                        self.data_to_send[target].insert(1, our_key)
                        self.data_to_send_id[target].insert(1, -2)
                    self.lock.release()

                sockets_to_remove = []
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
                        sockets_to_remove.append(target)
                        break

                    if self.data_to_send[target]:
                        to_delete = []
                        msg_idx = []
                        self.lock.acquire()
                        for idx, data in enumerate(self.data_to_send[target]):
                            # Add encryption if activated
                            not_header = self.data_to_send_id[target][idx] >= 0
                            if self.sockets_config[target] & SOCKET_CONFIG.SECURE and not_header:
                                try:
                                    data = self.crypto_boxes[target].encrypt(data)
                                except KeyError:
                                    # remote key not received
                                    continue

                            # Add the header
                            if self.data_to_send_id[target][idx] == -3:
                                data_header = struct.pack('!IH', 0, self.send_msg_idx[target])
                                msg_idx.append((0, self.send_msg_idx[target]))
                                self.send_msg_idx[target] += 1
                            elif self.data_to_send_id[target][idx] == -1:
                                data_header = b""
                            else:
                                data_header = struct.pack('!IH', len(data), self.send_msg_idx[target])
                                msg_idx.append((len(data), self.send_msg_idx[target]))
                                self.send_msg_idx[target] += 1

                            # Send the data
                            try:
                                if data_header:
                                    res = socket_.sendall(data_header)
                                res = socket_.sendall(data)
                            except (BrokenPipeError, OSError):
                                try:
                                    socket_.shutdown(2)    # 0 = done receiving, 1 = done sending, 2 = both
                                    socket_.close()
                                except OSError:
                                    # Socket was already closed
                                    pass
                                sockets_to_remove.append(target)
                                break
                            to_delete.append(idx)
                        for id_idx, idx in enumerate(to_delete):
                            self.data_awaiting[target].append((msg_idx[id_idx], self.data_to_send[target][idx]))
                            self.data_awaiting_id[target].append(self.data_to_send_id[target][idx])
                        for idx in reversed(to_delete):
                            self.data_to_send[target].pop(idx)
                            self.data_to_send_id[target].pop(idx)
                        self.lock.release()

                for sock in sockets_to_remove:
                    self.sockets.pop(sock, None)

                for target, socket_ in self.sockets.items():
                    self.lock.acquire()
                    try:
                        self.data_received[target].extend(socket_.recv(4096))
                    except socket.error:
                        pass

                    # Receive and process the connection header
                    if not self.client_header_received[target]:
                        self.client_header_received[target] = self.recv(source=target, timeout=0, _locks=False)

                    if self.secure and not target in self.crypto_boxes:
                        source_key = self.recv(source=target, timeout=0, _locks=False)
                        if source_key:
                            self.crypto_boxes[target] = security.getBox(source_key, target)

                    self.lock.release()
            try:
                _, _, _ = select.select(self.sockets.values(), [], [], self.poll_delay)
            except (OSError, ValueError):
                pass
