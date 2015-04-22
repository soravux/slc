from slc import Socket
import time


def example1():
    a, b = Socket(), Socket()

    a.listen() # Creating a server is done with .listen()
    b.connect(a.port) # Creating a client is done with .connect()

    b.send('An example.')
    data = a.receive()
    print("Data received:", data)


def example2():
    # Testing sending from the server

    c = Socket()
    d = Socket()

    # You can specify the port and listening address
    c.listen(27182, '0.0.0.0')
    d.connect(27182, '127.0.0.1')

    time.sleep(0.1) # Wait for the server to receive the connection from the client

    # You can send from the server to the client.
    # To send to a particular target, the tuple of (address, port) is required.
    d.send('Another example', ('127.0.0.1', 27182))
    data = c.receive()
    print(data)

def example3():
    # Testing broadcast

    e = Socket()
    f = Socket()
    g = Socket()

    e.listen(14142)
    f.connect(14142)
    g.connect(14142)

    time.sleep(0.1)

    e.send(b'broadcast')
    print(f.receive())
    print(g.receive())


def example4():
    # Testing multiple connection sending by a client

    h = Socket()
    i = Socket()
    j = Socket()
    h.listen(16180)
    i.listen(12020)
    j.connect(16180)
    j.connect(12020)

    time.sleep(0.1)

    j.send(b'Patate')
    print(h.receive())
    print(i.receive())

if __name__ == '__main__':
    example1()
    example2()
    example3()
    example4()








