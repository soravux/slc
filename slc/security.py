import os
import string
import errno
import logging

logger = logging.getLogger("slc")

try:
    import libnacl
    import libnacl.utils
except (ImportError, OSError):
    logger = logging.getLogger("slc")
    logger.warning("Could not load libnacl. Secure sockets won't be available.")


class PossibleSecurityBreach(Exception):
    pass


jn = os.path.join
slc_path = jn(os.path.expanduser('~'), '.slc')
key_path = jn(slc_path, '0.0.0.0')


def initializeSecurity():
    global hostkey
    # Check if user has a .slc directory to hold the keys
    try:
        os.makedirs(slc_path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise
    
    # Create a secret key for the host if not already done
    if not os.path.isfile(key_path):
        logger.warning('First time using security. Building key for this host.')
        hostkey = libnacl.public.SecretKey()
        hostkey.save(key_path)
    else:
        hostkey = libnacl.utils.load_key(key_path)


def stringToFilename(data):
    valid_chars = "-_.%s%s" % (string.ascii_letters, string.digits)
    return ''.join(c for c in data if c in valid_chars)


def getTargetKey(target):
    target = stringToFilename(str(target[0]))
    target_key_path = (jn(slc_path, target))
    if os.path.isfile(target_key_path):
        with open(target_key_path, 'rb') as fhdl:
            return fhdl.read()


def validateTargetKey(remoteKey, target):
    key_already_here = getTargetKey(target)
    if key_already_here is not None:
        if key_already_here != remoteKey:
            raise PossibleSecurityBreach('The key sent by the peer is not the '
                                         'same as the one already on the '
                                         'system.')
    else:
        with open(target_key_path, 'wb') as fhdl:
            fhdl.write(remoteKey)
        logger.warning('Added key for {} in wallet.'.format(target))


def getBox(remoteKey, target):
    validateTargetKey(remoteKey, target)
    return libnacl.public.Box(hostkey.sk, remoteKey)


def getOurPublicKey():
    if 'hostkey' not in globals():
        initializeSecurity()
    return hostkey.pk