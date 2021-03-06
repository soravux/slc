import time
import threading
import struct

import pytest

from slc import Communicator as Comm
from slc import (COMP_ZLIB_DEFAULT, COMP_ZLIB_MAX, SER_PICKLE_HIGHEST)


data = [
    b'Not all those who wander are lost.',
    b'Time is a drug. Too much of it kills you.',
    'The mirror does not reflect evil, but creates it.',
    42,
]


second_data = [
    b'Time is a drug. Too much of it kills you.',
    123,
    'The mirror does not reflect evil, but creates it.',
]


def test_ShutdownSimple():
    a = Comm()

    a.shutdown()

    assert threading.active_count() <= 1


def test_ShutdownClientServer():
    a = Comm()
    b = Comm()
    a.listen(31415)
    b.connect(31415)

    b.shutdown()
    a.shutdown()

    assert threading.active_count() <= 1


def test_ShutdownMultiple():
    a = Comm()
    b = Comm()
    c = Comm()
    a.listen(27182)
    b.connect(27182)
    c.connect(27182)

    c.shutdown()
    b.shutdown()
    a.shutdown()

    assert threading.active_count() <= 1


@pytest.mark.parametrize("data_in", data)
def test_SendToServer(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.recv(timeout=0.5)
    assert data_in == data_out

    b.shutdown(); a.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_SendToSingleClient(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    a.send(data_in)
    data_out = b.recv(timeout=0.5)
    assert data_in == data_out

    a.shutdown(); b.shutdown()

@pytest.mark.parametrize("data_in", data)
def test_SendToAllClients(data_in):
    # Testing broadcast

    a = Comm()
    b = Comm()
    c = Comm()

    a.listen()
    b.connect(a.port)
    c.connect(a.port)

    a.send(data_in)
    data_out1, data_out2 = b.recv(timeout=0.5), c.recv(timeout=0.5)
    assert data_in == data_out1 == data_out2

    a.shutdown(); b.shutdown(); c.shutdown()

@pytest.mark.parametrize("data_in", data)
def test_SendToAllServers(data_in):
    # Testing multiple connection sending by a client
    a = Comm()
    b = Comm()
    c = Comm()
    a.listen()
    b.listen()
    c.connect(a.port)
    c.connect(b.port)

    c.send(data_in)
    data_out1, data_out2 = a.recv(timeout=0.5), b.recv(timeout=0.5)
    assert data_in == data_out1
    assert data_in == data_out2

    a.shutdown(); b.shutdown(); c.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_SendTarget(data_in):
    a = Comm()
    b = Comm()
    c = Comm()
    a.listen()
    b.listen()
    c.connect(a.port)
    c.connect(b.port)

    target = ('127.0.0.1', a.port)

    c.send(data_in, target=target)
    data_out1, data_out2 = a.recv(timeout=0.5), b.recv(timeout=0.1)
    assert data_out1 == data_in
    assert data_out2 is None

    a.shutdown(); b.shutdown(); c.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_SendMultipleTargets(data_in):
    a = Comm()
    b = Comm()
    c = Comm()
    d = Comm()
    a.listen()
    b.listen()
    c.listen()
    d.connect(a.port)
    d.connect(b.port)
    d.connect(c.port)

    targets = [('127.0.0.1', a.port), ('127.0.0.1', b.port)]

    d.send(data_in, target=targets)
    data_out1, data_out2, data_out3 = a.recv(timeout=0.5), b.recv(timeout=0.5), c.recv(timeout=0.1)
    assert data_in == data_out1
    assert data_in == data_out2
    assert data_out3 is None

    a.shutdown(); b.shutdown(); c.shutdown(); d.shutdown()


@pytest.mark.parametrize("data_in1,data_in2", zip(data, second_data))
def test_SendMultipleData(data_in1, data_in2):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    b.send(data_in1)
    b.send(data_in2)

    data_out1, data_out2 = a.recv(timeout=0.5), a.recv(timeout=0.5)

    assert data_in1 == data_out1
    assert data_in2 == data_out2

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_noTarget(data_in):
    a = Comm()
    a.send(data_in)


@pytest.mark.parametrize("data_in", data)
def test_wrongTarget(data_in):
    a = Comm()
    random_target = ('127.1.1.5', 32323)
    with pytest.raises(KeyError):
        a.send(data_in, target=random_target)


def test_SendMultipleDataMultipleClient():
    a = Comm()
    b = Comm()
    c = Comm()
    d = Comm()
    e = Comm()
    a.listen()
    b.connect(a.port)
    c.connect(a.port)
    d.connect(a.port)
    e.connect(a.port)

    b.send(data[0])
    data_out = a.recv(timeout=0.5)
    assert data_out == data[0]

    c.send(data[1])
    data_out = a.recv(timeout=0.5)
    assert data_out == data[1]

    d.send(data[2])
    e.send(data[3])
    data_out1 = a.recv(timeout=0.5)
    data_out2 = a.recv(timeout=0.5)
    assert data_out1 in data[2:]
    assert data_out2 in data[2:]

    a.shutdown(); b.shutdown(); c.shutdown(); d.shutdown(); e.shutdown()


def test_SendMultipleDataMultipleClientWithTarget():
    a = Comm()
    b = Comm()
    c = Comm()
    d = Comm()
    e = Comm()
    a.listen()
    b.connect(a.port)
    c.connect(a.port)
    d.connect(a.port)
    e.connect(a.port)

    b.send(data[0])
    data_out = a.recv(timeout=0.5)
    assert data_out == data[0]

    c.send(data[1])
    data_out = a.recv(timeout=0.5)
    assert data_out == data[1]

    d.send(data[2])
    e.send(data[3])
    data_out1 = a.recv(timeout=0.5, source=("127.0.0.1", e.port))
    data_out2 = a.recv(timeout=0.5, source=("127.0.0.1", d.port))
    assert data_out1 in data[2:]
    assert data_out2 in data[2:]

    a.shutdown(); b.shutdown(); c.shutdown(); d.shutdown(); e.shutdown()


def test_SendMultipleData():
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    for y in range(10):
        for x in data:
            b.send(x)

    for y in range(10):
        for x in data:
            data_out = a.recv(timeout=0.5)
            assert x == data_out

    a.shutdown(); b.shutdown()


def test_CreateTwoServersBackToBack():
    a = Comm()
    b = Comm()
    c = Comm()

    a.listen()
    a.shutdown()
    b.listen(a.port)
    c.connect(b.port)

    c.send(data[0])
    data_out = b.recv(timeout=0.5)
    assert data[0] == data_out

    a.shutdown(); b.shutdown(); c.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_securityClient(data_in):
    a = Comm(secure=True)
    b = Comm(secure=True)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.recv(timeout=0.5)
    b.recv(timeout=0.5) # Test the acknowledgment
    assert data_out == data_in

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_securityServer(data_in):
    a = Comm(secure=True)
    b = Comm(secure=True)

    a.listen()
    b.connect(a.port)

    a.send(data_in)
    data_out = b.recv(timeout=0.5)
    a.recv(timeout=0.5) # Test the acknowledgment
    assert data_out == data_in

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_compression(data_in):
    a = Comm(compress=COMP_ZLIB_DEFAULT)
    b = Comm(compress=COMP_ZLIB_DEFAULT)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.recv(timeout=0.5)
    assert data_out == data_in

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_compressionAndSecure(data_in):
    a = Comm(compress=COMP_ZLIB_DEFAULT, secure=True)
    b = Comm(compress=COMP_ZLIB_DEFAULT, secure=True)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.recv(timeout=0.5)
    assert data_out == data_in

    a.shutdown(); b.shutdown()


def test_wronglyConfiguredComm():
    a = Comm(compress=COMP_ZLIB_DEFAULT)
    b = Comm(compress=None)
    a.listen()
    with pytest.raises(AssertionError):
        b.connect(a.port)


@pytest.mark.parametrize("data_in", data)
def test_disconnect(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    target_b = ('127.0.0.1', a.port)
    target_a = ('127.0.0.1', list(b.sockets.values())[0].getsockname()[1])
    data_in = 'disconnect test'

    b.send(data_in)
    
    # Simulate a loss of connection and packet
    time.sleep(0.1)
    b.sockets[target_b].shutdown(2)
    try:
        b.sockets[target_b].close()
    except KeyError:
        pass
    a.data_received.pop(target_a, None)
    a.sockets[target_a].shutdown(2)
    try:
        a.sockets[target_a].close()
    except KeyError:
        pass

    data_out = a.recv(timeout=0.5)
    assert data_out == data_in

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_multipleListen(data_in):
    a = Comm()
    b = Comm()

    a.listen(12340)
    a.listen(12341)
    b.connect(12340)
    b.connect(12341)

    data_in = "test data"
    b.send(data_in)
    data_out1, data_out2 = a.recv(timeout=0.5), a.recv(timeout=0.5)
    assert data_in == data_out1
    assert data_in == data_out2

    a.shutdown(); b.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_asynchronousConnect(data_in):
    a = Comm()
    b = Comm()

    a.listen()
    b.connect(a.port, timeout=0)

    data_in = "test data"
    b.send(data_in)
    data_out = a.recv(timeout=0.5)
    assert data_in == data_out


def test_discover():
    a = Comm()
    b = Comm()
    a.listen()
    a.advertise("a_test")
    res = b.discover()

    assert len(res) >= 1

    a.stopAdvertising()


def test_discover_specific():
    a = Comm()
    b = Comm()
    c = Comm()
    a.listen()
    c.listen()
    a.advertise("b_test")
    c.advertise("other_test")
    res = b.discover("b_test")

    assert len(res) == 1

    a.stopAdvertising()


@pytest.mark.parametrize("data_in", data)
def test_messageIDSimple(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    mid = b.send(data_in)

    assert b.is_acknowledged(mid) == False

    data_out = a.recv(timeout=0.5)
    b.recv(timeout=0.5)

    assert data_out == data_in
    assert b.is_acknowledged(mid) == True


@pytest.mark.parametrize("data_in", data)
def test_messageIDNonListening(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)
    a.shutdown()

    mid = b.send(data_in)
    b.recv(timeout=0.5)

    assert b.is_acknowledged(mid) == False


@pytest.mark.parametrize("data_in", data)
def test_messageIDInterruption(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    serv_port = a.port
    b.connect(serv_port)
    a.shutdown()

    mid = b.send(data_in)
    b.recv(timeout=0.5)

    assert b.is_acknowledged(mid) == False

    a.listen(serv_port)
    b.recv(timeout=0.5)

    assert b.is_acknowledged(mid) == False

    a.recv(timeout=0.5)
    b.recv(timeout=0.5)

    assert b.is_acknowledged(mid) == True


@pytest.mark.parametrize("data_in", data)
def test_receiveAddress(data_in):
    a = Comm()
    b = Comm()
    a.listen()
    b.connect(a.port)

    mid = a.send(data_in)
    src, data_out = b.receive(timeout=0.5)

    assert data_out == data_in
    assert src == ("127.0.0.1", a.port)


if __name__ == '__main__':
    pass