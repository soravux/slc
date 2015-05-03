import time
import threading
import struct

import pytest

from slc import Socket


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
    a = Socket()

    a.shutdown()

    assert threading.active_count() <= 1

def test_ShutdownClientServer():
    a = Socket()
    b = Socket()
    a.listen(31415)
    b.connect(31415)

    b.shutdown()
    a.shutdown()

    assert threading.active_count() <= 1


def test_ShutdownMultiple():
    a = Socket()
    b = Socket()
    c = Socket()
    a.listen(27182)
    b.connect(27182)
    c.connect(27182)

    c.shutdown()
    b.shutdown()
    a.shutdown()

    assert threading.active_count() <= 1


@pytest.mark.parametrize("data_in", data)
def test_SendToServer(data_in):
    a = Socket()
    b = Socket()
    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.receive()
    assert data_in == data_out

    b.shutdown(); a.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_SendToSingleClient(data_in):
    a = Socket()
    b = Socket()
    a.listen()
    b.connect(a.port)

    a.send(data_in)
    data_out = b.receive()
    assert data_in == data_out

    a.shutdown(); b.shutdown()

@pytest.mark.parametrize("data_in", data)
def test_SendToAllClients(data_in):
    # Testing broadcast

    a = Socket()
    b = Socket()
    c = Socket()

    a.listen()
    b.connect(a.port)
    c.connect(a.port)

    a.send(data_in)
    data_out1, data_out2 = b.receive(), c.receive()
    assert data_in == data_out1 == data_out2

    a.shutdown(); b.shutdown(); c.shutdown()

@pytest.mark.parametrize("data_in", data)
def test_SendToAllServers(data_in):
    # Testing multiple connection sending by a client

    a = Socket()
    b = Socket()
    c = Socket()
    a.listen()
    b.listen()
    c.connect(a.port)
    c.connect(b.port)

    c.send(data_in)
    data_out1, data_out2 = a.receive(), b.receive()
    assert data_in == data_out1
    assert data_in == data_out2

    a.shutdown(); b.shutdown(); c.shutdown()

@pytest.mark.parametrize("data_in1,data_in2", zip(data, second_data))
def test_SendMultipleData(data_in1, data_in2):
    a = Socket()
    b = Socket()
    a.listen()
    b.connect(a.port)

    b.send(data_in1)
    b.send(data_in2)

    data_out1, data_out2 = a.receive(), a.receive()

    assert data_in1 == data_out1
    assert data_in2 == data_out2

    a.shutdown(); b.shutdown()


def test_SendMultipleData():
    a = Socket()
    b = Socket()
    a.listen()
    b.connect(a.port)

    for y in range(10):
        for x in data:
            b.send(x)

    for y in range(10):
        for x in data:
            data_out = a.receive()
            assert x == data_out

    a.shutdown(); b.shutdown()


def test_CreateTwoServersBackToBack():
    a = Socket()
    b = Socket()
    c = Socket()

    a.listen()
    a.shutdown()
    b.listen(a.port)
    c.connect(b.port)

    c.send(data[0])
    data_out = b.receive()
    assert data[0] == data_out

    b.shutdown(); c.shutdown()


@pytest.mark.parametrize("data_in", data)
def test_Security(data_in):
    a = Socket(secure=True)
    b = Socket(secure=True)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.receive()
    assert data_out == data_in


@pytest.mark.parametrize("data_in", data)
def test_compression(data_in):
    a = Socket(compress=True)
    b = Socket(compress=True)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.receive()
    assert data_out == data_in


@pytest.mark.parametrize("data_in", data)
def test_compressionAndSecure(data_in):
    a = Socket(compress=True, secure=True)
    b = Socket(compress=True, secure=True)

    a.listen()
    b.connect(a.port)

    b.send(data_in)
    data_out = a.receive()
    assert data_out == data_in


def test_wronglyConfiguredSocket():
    raise NotImplementedError()


def test_disconnect():
    a = Socket()
    b = Socket()
    a.listen()
    b.connect(a.port)

    time.sleep(0.1)

    target = ('127.0.0.1', a.port)
    sock = b.sockets[target]
    data_in = 'disconnect test'

    data_serialized = b._prepareData(data_in, target)
    data_header = struct.pack('!IH', len(data_serialized), b.send_msg_idx[target])
    b.send_msg_idx[target] += 1

    sock.shutdown(2)
    sock.close()

    b.data_awaiting[target].append(data_header + data_serialized)

    data_out = a.receive()
    assert data_out == data_in

    a.shutdown(); b.shutdown()


def test_multipleTargets():
    raise NotImplementedError()


def test_singleTarget():
    raise NotImplementedError()


def test_wrongTarget():
    raise NotImplementedError()
    #a = Socket()
    #a.connect(8080, "127.1.2.3")
    #time.sleep(2)


def test_simultaneousListenConnect():
    raise NotImplementedError()


def test_multipleListen():
    a = Socket()
    b = Socket()

    a.listen(12340)
    a.listen(12341)
    b.connect(12340)
    b.connect(12341)

    data_in = "test data"
    b.send(data_in)
    data_out1, data_out2 = a.receive(), a.receive()
    assert data_in == data_out1
    assert data_in == data_out2


def test_asynchronousConnect():
    a = Socket()
    b = Socket()

    a.listen()
    b.connect(a.port, timeout=0)

    data_in = "test data"
    b.send(data_in)
    data_out = a.receive()
    assert data_in == data_out


def test_discover():
    a = Socket()
    b = Socket()
    a.listen()
    a.advertise("test_type", "test_name", "test_advertiser")
    time.sleep(0.5)
    res = b.discover("test_type", "test_name")
    print(res)

# TODO: Add tests for:
# - Disconnection
# - Discovery & Advertisement

if __name__ == '__main__':
    test_discover() 