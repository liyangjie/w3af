'''
HTTPRequestParser.py

Copyright 2008 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import urlparse

from core.data.parsers.url import URL
from core.data.dc.headers import Headers
from core.data.request.factory import create_fuzzable_request_from_parts
from core.controllers.exceptions import w3afException


def check_version_syntax(version):
    '''
    @return: True if the syntax of the version section of HTTP is valid; else
             raise an exception.

    >>> check_version_syntax('HTTP/1.0')
    True

    >>> check_version_syntax('HTTPS/1.0')
    Traceback (most recent call last):
      File "<stdin>", line 1, in ?
    w3afException: The HTTP request has an invalid HTTP token in the version specification: "HTTPS/1.0"

    >>> check_version_syntax('HTTP/1.00000000000000')
    Traceback (most recent call last):
      File "<stdin>", line 1, in ?
    w3afException: HTTP request version "HTTP/1.00000000000000" is unsupported

    >>> check_version_syntax('ABCDEF')
    Traceback (most recent call last):
      File "<stdin>", line 1, in ?
    w3afException: The HTTP request has an invalid version token: "ABCDEF"
    '''
    supportedVersions = ['1.0', '1.1']
    splittedVersion = version.split('/')

    if len(splittedVersion) != 2:
        msg = 'The HTTP request has an invalid version token: "' + \
            version + '"'
        raise w3afException(msg)
    elif len(splittedVersion) == 2:
        if splittedVersion[0].lower() != 'http':
            msg = 'The HTTP request has an invalid HTTP token in the version specification: "'
            msg += version + '"'
            raise w3afException(msg)
        if splittedVersion[1] not in supportedVersions:
            raise w3afException(
                'HTTP request version "' + version + '" is unsupported')
    return True


def check_uri_syntax(uri, host=None):
    '''
    @return: True if the syntax of the URI section of HTTP is valid; else
             raise an exception.

    >>> check_uri_syntax('http://abc/def.html')
    'http://abc/def.html'

    >>> check_uri_syntax('ABCDEF')
    Traceback (most recent call last):
      File "<stdin>", line 1, in ?
    w3afException: You have to specify the complete URI, including the protocol and the host. Invalid URI: ABCDEF
    '''
    supported_schemes = ['http', 'https']
    scheme, domain, path, params, qs, fragment = urlparse.urlparse(uri)
    scheme = scheme.lower()

    if not scheme:
        scheme = 'http'
    if not domain:
        domain = host
    if not path:
        path = '/'

    if scheme not in supported_schemes or not domain:
        msg = 'You have to specify the complete URI, including the protocol and the host.'
        msg += ' Invalid URI: ' + uri
        raise w3afException(msg)

    res = urlparse.urlunparse((scheme, domain, path, params, qs, fragment))
    return res


def HTTPRequestParser(head, postdata):
    '''
    This function parses HTTP Requests from a string to a FuzzableRequest.

    @param head: The head of the request.
    @param postdata: The post data of the request
    @return: A FuzzableRequest object with all the corresponding information
        that was sent in head and postdata

    @author: Andres Riancho (andres.riancho@gmail.com)

    '''
    # Parse the request head, the strip() helps us deal with the \r (if any)
    splitted_head = head.split('\n')
    splitted_head = [h.strip() for h in splitted_head if h]

    if not splitted_head:
        msg = 'The HTTP request is invalid.'
        raise w3afException(msg)

    # Get method, uri, version
    method_uri_version = splitted_head[0]
    first_line = method_uri_version.split(' ')
    if len(first_line) == 3:
        # Ok, we have something like "GET /foo HTTP/1.0". This is the best case for us!
        method, uri, version = first_line
    elif len(first_line) < 3:
        msg = 'The HTTP request has an invalid <method> <uri> <version> token: "'
        msg += method_uri_version + '".'
        raise w3afException(msg)
    elif len(first_line) > 3:
        # GET /hello world.html HTTP/1.0
        # Mostly because we are permissive... we are going to try to parse
        # the request...
        method = first_line[0]
        version = first_line[-1]
        uri = ' '.join(first_line[1:-1])

    check_version_syntax(version)

    # If we got here, we have a nice method, uri, version first line
    # Now we parse the headers (easy!) and finally we send the request
    headers_str = splitted_head[1:]
    headers_inst = Headers()
    for header in headers_str:
        one_splitted_header = header.split(':', 1)
        if len(one_splitted_header) == 1:
            raise w3afException(
                'The HTTP request has an invalid header: "' + header + '"')

        header_name = one_splitted_header[0].strip()
        header_value = one_splitted_header[1].strip()
        if header_name in headers_inst:
            headers_inst[header_name] += ', ' + header_value
        else:
            headers_inst[header_name] = header_value

    host, _ = headers_inst.iget('host', None)

    uri = URL(check_uri_syntax(uri, host))

    return create_fuzzable_request_from_parts(uri, method, postdata,
                                              headers_inst)
