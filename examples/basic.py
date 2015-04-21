from slc import Socket
import time

# Testing sending form client

a = Socket()
b = Socket()

print("listen")
a.listen(31415)
print("connect")
b.connect(31415)

print("send")
b.send(b'test')
print("receive")
data = a.receive()
print("Data received:")
print(data)

# Testing sending from the server

c = Socket()
d = Socket()

print("listen")
c.listen(27182)
print("connect")
d.connect(27182)

time.sleep(0.1) # Wait for the server to receive the connection from the client

print("send")
d.send(b'Poulailler', '127.0.0.1')
print("receive")
data = c.receive()
print("Data received:")
print(data)

# Testing broadcast

e = Socket()
f = Socket()
g = Socket()

print("Listen")
e.listen(14142)
print("Connect 1")
f.connect(14142)
print("Connect 2")
g.connect(14142)

time.sleep(0.1)

print("Sending")
e.send(b'broadcast')
print("Recv 1")
print(f.receive())
print("Recv 2")
print(g.receive())


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

