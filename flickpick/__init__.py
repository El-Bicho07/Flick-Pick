import socket

# Ensure IPv4 resolution for TMDB domains to prevent broken dual-stack IPv6 route resets
_ORIG_GETADDRINFO = socket.getaddrinfo

def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host and ('themoviedb.org' in str(host) or 'tmdb.org' in str(host)):
        return _ORIG_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
    return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv4_preferred_getaddrinfo
