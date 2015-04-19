# SLC
Simple Lightweight Communications

## Features (work in progress)

* Simple and Lightweight
* Allows one-to-one and one-to-many (publisher - subscriber) communications
* Auto-reconnection on connection lost (TODO)
* Zero Configuration, service discovery (TODO)
* Throttling (TODO)
* Security (TODO)
* RPC (TODO)
* Support multiple backends (RDMA, UDP, IGMP, ...)

## API TODO

* Accept anything in send input
* Allow multiple listen from a single socket
* Allow socket to listen and connect at the same time (wouldn't that be a bit complex?)
* Add source of message in receive()