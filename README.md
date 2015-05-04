# SLC
Simple Lightweight Communications

## Example

```python
from slc import Socket

a, b, c, d = Socket(), Socket(), Socket(), Socket()
a.listen(31415) # listen() makes a server
b.listen(27182) # By default, listen on every interface
c.connect(31415, '127.0.0.1') # connect() makes a client
d.connect(31415, '127.0.0.1')
d.connect(27182, '127.0.0.1') # Multiple connects on a single socket are supported

# Send from client (c) to server (a)
c.send(b'Not all those who wander are lost.')
data = a.receive()

# Publish from server (a) to clients (c, d)
a.send(b'Time is a drug. Too much of it kills you.')
data1, data2 = c.receive(), d.receive()

# Publish from client (d) to servers (a, b)
d.send(b'The mirror does not reflect evil, but creates it.')
data1, data2 = a.receive(), b.receive()
```

## Features (work in progress)

* Simple, Lightweight and Portable
* Allows one-to-one and one-to-many (publisher - subscriber) communications
* Compression
* Security
* Auto-reconnection on connection lost, no message lost
* Zero Configuration, service discovery
* Support multiple backends (RDMA, UDP, IGMP, ...) (TODO)
* Throttling (TODO)

## API TODO

* Add source of message in receive()
* Add support for asynchronous connection
* Support data more than 2**32 and more than 2**16 packets
* Add a way to allow users to choose advanced values (ie. compression level, encryption algorithm)

## Choices

* Serialization
** Pickle? JSON? MessagePack? Fallbacks from one to another?
