#!/usr/bin/env python

import itertools
import time
from select import select
from socket import (socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_BROADCAST,
    gethostbyname, gethostname, SO_REUSEADDR, SHUT_RDWR)


PORT = 60221
MAGIC = b"CL4Ck$"



def discover():
    """Send a discovery probe and listen for result."""
    s = socket(AF_INET, SOCK_DGRAM)
    s.bind(('', 0))
    s.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
    # TODO: Make this work on multiple interfaces / IPs.
    #ip = gethostbyname(gethostname())

    data = MAGIC # + ip
    s.sendto(data, ('<broadcast>', PORT))
    time.sleep(1)

    results = []
    while select([s], [], [], 0)[0]:
        data, addr = s.recvfrom(1024)
        if data.startswith(MAGIC):
            results.append(tuple(itertools.chain.from_iterable((
                data[len(MAGIC):].decode('utf-8').split(','), (addr[0],)))))
    return results


def advertise(name, ports, cond):
    """Advertise until the cond (threading.Event) is set.

    This function supposes the packet won't be split, which should be the case
    on a LAN."""
    s = socket(AF_INET, SOCK_DGRAM)
    s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    s.bind(('', PORT))
    s.setblocking(0)
    s.settimeout(0.1)

    tosend = MAGIC + (name + "," + ports).encode('utf-8')

    while not cond.wait(0.1):
        if select([s], [], [], 0)[0]:
            data, addr = s.recvfrom(1024)
            if data.startswith(MAGIC):
                s.sendto(tosend, addr)

    s.shutdown(SHUT_RDWR)
    s.close()