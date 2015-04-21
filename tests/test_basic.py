import time
import threading

import pytest

from slc import Socket


data = [
    b'Not all those who wander are lost.',
    b'Time is a drug. Too much of it kills you.',
    b'The mirror does not reflect evil, but creates it.',
    'Not all those who wander are lost.',
    15,
]


second_data = [
    b'Time is a drug. Too much of it kills you.',
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

    time.sleep(0.1) # Wait for the server to receive the connection from the client

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

    time.sleep(0.1)
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

    time.sleep(0.1)
    c.send(data_in)
    data_out1, data_out2 = a.receive(), b.receive()
    assert data_in == data_out1 == data_out2

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


if __name__ == '__main__':
    test_CreateTwoServersBackToBack()