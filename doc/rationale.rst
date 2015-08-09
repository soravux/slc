Rationale
=========

Why SLC?
-----------

In our opinion, Python (and the world) lacks a simple, decentralized lightweight socket-layer all-in-one facilities. A library that *just works*, simply and coherently.

Who wants SLC?
--------------

Anyone jealous of the HTTP facilities like `requests <http://www.python-requests.org/>`_ and wonder why basic communication couldn't be this simple.

SLC vs sockets
--------------

SLC can be seen as standard `sockets <https://docs.python.org/library/socket.html>`_ on steroids. Standard sockets are pretty primitive, requiring you to analyze all the possible behaviors of these low-level objects. This includes a tedious configuration or polling to get the right (non-)blocking behavior, looping over received packets to reconstruct your string that was potentially split up by a network switch and many more. Also, it limits you to point-to-point communications.

On the other hand, SLC provide intuitive default behavior and configuration while keeping the basic simplicity of sockets: connect, send and receive.

SLC vs Message Queuing
----------------------

Message queuing libraries enables the interaction with an higher level of abstraction in communication. To the user, it simplifies a communication tunnel to a queue, allowing messages to be the equivalent to an element in the queue.

Some of these libraries (such as `rabbitmq <https://www.rabbitmq.com/>`_ or `redis-mq <http://python-rq.org/>`_) offer a centralized `database` (a broker) holding the messages until they are delivered and require binary executables that may be cumbersome to setup.

Other decentralized (brokerless) libraries, mainly `zeromq <http://zeromq.org/>`_, are quite complex to operate and doesn't quite make the cut for use case other than web services. This can be shown by some lost features of the basic socket, such as the inability to recover a port assigned by the OS. ZeroMQ is so complex, than their authors decided to create a more lightweight alternative called `nanomsg <http://nanomsg.org/>`_.

Other message queuing libraires, as `snakemq <http://www.snakemq.net/>`_ are certainly good for their use case. Their relative high-level approach simplifies the socket to a queue, which may be a problem if you need a socket-like interface. If you want to keep it simple, connect, send and receive, then Message Queues are not exactly the right match.

SLC vs Twisted
--------------

Event-driven frameworks such as Twisted allows the developers to focus on what to do with the data once it arrives. This is perfect for web-based applications or similar, but in an application where networking is only a part of the solution, this paradigm may be an hinderance. The framework requires the developper to use its internal run or loop function to handle the events, which can be quite limiting compared to bare sockets.