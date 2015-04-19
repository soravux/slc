from slc import Socket
import time

a = Socket()
b = Socket()

print("listen")
a.listen(31415)
print("connect")
b.connect(31415)

print("send")
b.send(b'test', '127.0.0.1')
print("receive")
data = a.receive()
print("Data received:")
print(data)

c = Socket()
d = Socket()

print("listen")
c.listen(27182)
print("connect")
d.connect(27182)

time.sleep(0.1)

print("send")
d.send(b'Poulailler', '127.0.0.1')
print("receive")
data = c.receive()
print("Data received:")
print(data)