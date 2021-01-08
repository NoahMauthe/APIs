"""
read_int, to_big_int and encrypt_password are taken from https://github.com/NoMore201/googleplay-api
"""

import logging
import struct
from base64 import b64decode, urlsafe_b64encode
from time import sleep

import toml
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives.asymmetric import padding
from requests import post
from requests import get as default_get

from API.Objects import SubCategory, Category
from API.Exceptions import AuthenticationError, TokenError

LOGGER = logging.getLogger('Crawler.Utils')
LOGGER.setLevel(logging.INFO)

SSL_VERIFY = True

GOOGLE_PUBKEY = "AAAAgMom/1a/v0lblO2Ubrt60J2gcuXSljGFQXgcyZWveWLEwo6prwgi3iJIZdodyhKZQrNWp5nKJ3srRXcUW" \
                "+F1BD3baEVGcmEgqaLZUNBjm057pKRI16kB0YppeGx5qIQ5QjKzsR8ETQbKLNWgRY0QRNVz34kMJR3P/LgHax" \
                "/6rmf5AAAAAwEAAQ== "

VERBOSE = False


def read_int(byte_array, start):
    """Read the byte array, starting from *start* position,
    as an 32-bit unsigned integer"""
    return struct.unpack("!L", byte_array[start:][0:4])[0]


def to_big_int(byte_array):
    """Convert the byte array to a BigInteger"""
    array = byte_array[::-1]  # reverse array
    out = 0
    for key, value in enumerate(array):
        decoded = struct.unpack("B", bytes([value]))[0]
        out = out | decoded << key * 8
    return out


def encrypt_password(user, password):
    """Encrypt credentials using the google public key, with the
    RSA algorithm"""

    # structure of the binary key:
    #
    # *-------------------------------------------------------*
    # | modulus_length | modulus | exponent_length | exponent |
    # *-------------------------------------------------------*
    #
    # modulus_length and exponent_length are uint32
    binary_key = b64decode(GOOGLE_PUBKEY)
    # modulus
    i = read_int(binary_key, 0)
    modulus = to_big_int(binary_key[4:][0:i])
    # exponent
    j = read_int(binary_key, i + 4)
    exponent = to_big_int(binary_key[i + 8:][0:j])

    # calculate SHA1 of the pub key
    digest = hashes.Hash(hashes.SHA1(), backend=default_backend())
    digest.update(binary_key)
    h = b'\x00' + digest.finalize()[0:4]

    # generate a public key
    der_data = encode_dss_signature(modulus, exponent)
    pubkey = load_der_public_key(der_data, backend=default_backend())

    # encrypt email and password using pubkey
    to_be_encrypted = user.encode() + b'\x00' + password.encode()
    ciphertext = pubkey.encrypt(
        to_be_encrypted,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None
        )
    )

    return urlsafe_b64encode(h + ciphertext).decode('utf-8')


def verbose_post(url, data, headers=None, timeout=(5, 10), verify=True, proxies=None):
    """Wrapper function for requests.post.
        Accepts only the parameters specified below.

    Parameters
    ----------
    url : str
        The url to query.
    data : dict
        The parameters to apply to the url.
    headers : dict
        The parameters to apply to the request.
    timeout : float, tuple
        Either a float value or an (int, int) tuple to represent connection and reply timeout.
    verify : bool
        Set to false to allow unverified https requests.
        You should only use this for internal testing!
    proxies : dict
        A map from protocol to proxy.
    Returns
    -------
    Response
        A response object, just like requests.post would generate.
    """
    response = post(url, data=data, headers=headers, verify=verify, proxies=proxies, timeout=timeout)
    if VERBOSE:
        request = response.request
        LOGGER.debug('#' * 80)
        LOGGER.debug('REQUEST\n' + '-' * 20)
        LOGGER.debug(f'url {request.url}' + '\n')
        LOGGER.debug('\tHeaders:')
        for header in request.headers.keys():
            LOGGER.debug(f'\t\t{header}:\t{request.headers[header]}')
        LOGGER.debug('\tParameters:')
        try:
            for param in request.body.split('&'):
                k, v = param.split('=')
                LOGGER.debug(f'\t\t{k}:\t{v}')
        except TypeError:
            LOGGER.debug('\tBody')
            LOGGER.debug(f'\t\t{request.body}')
        LOGGER.debug('-' * 80)
        LOGGER.debug(f'RESPONSE - Status Code {response.status_code}: {response.reason}\n' + '-' * 20)
        LOGGER.debug('\tHeaders:')
        for header in response.headers:
            LOGGER.debug(f'\t\t{header}:\t{response.headers[header]}')
        LOGGER.debug('\tCookies:')
        for cookie in response.cookies:
            LOGGER.debug(f'\t\t{cookie}')
        LOGGER.debug('\tContent:')
        LOGGER.debug(f'\t\t{response.content}')
        if response.status_code != 200:
            LOGGER.warning(f'Status code for request {response.url} was {response.status_code} - {response.reason}')
    return response


def get_devices():
    """Lists the codenames of all available devices

    Returns
    -------
    KeysView
        The codenames as present in the devices file.
    """
    devices = toml.load('config/devices.toml')
    return devices.keys()


def get_token(response, name):
    """Retrieves a token from a http response.

    Parameters
    ----------
    response : Response
        The html response containing the token.
    name : str
        The name of the token to look for.

    Returns
    -------
    str
        The token.
    """
    token = None
    for line in response.text.split():

        try:
            k, v = line.split('=', 1)
            k = k.strip().lower()
            if k == name:
                token = v
                break
            elif k == 'error':
                raise AuthenticationError(v)
        except ValueError:
            pass
    if not token:
        raise TokenError('The server did not provide a token!')
    return token


def subcategory_list(data, parent):
    """Parses a protobuf response for subcategories.

    Parameters
    ----------
    data : Message
        A protobuf message containing subcategories.
    parent : Category
        The category to which the subcategories belong.

    Returns
    -------
    list
        A list of SubCategory objects.
    """
    categories = []
    for prefetch in data.preFetch:
        if 'ctr=' in prefetch.url:
            try:
                categories.append(SubCategory(prefetch, parent))
            except (IndexError, AttributeError):
                continue
    return categories


def category_list(data):
    """Parses a protobuf response for categories.

    Parameters
    ----------
    data : Message
        A protobuf message containing categories.

    Returns
    -------
    list
        A list of SubCategory objects.
    """
    categories = []
    for category in data.payload.browseResponse.category:
        categories.append(Category(category))
    return categories


def get(url, params=None, timeout=(5, 10), **kwargs):
    """Wrapper for requests.get to handle rate limiting and service availability
        All parameters are handled in the same way as for requests.get

    Parameters
    ----------
    url : str
        The url to query.
    params : dict
        The parameters to apply to the url.
    timeout : float, tuple
        Either a float value or an (int, int) tuple to represent connection and reply timeout.
    kwargs : Any
        Keyword arguments, directly passed to requests.get.
    Returns
    -------
    Response
        A response object, just like requests.get would.
    """
    status_code = 429
    wait = 0
    response = None
    while status_code == 429:
        sleep(wait)
        try:
            response = default_get(url, params=params, timeout=timeout, **kwargs)
        except ConnectionError:
            LOGGER.error(f'Connection failed for URL {url}')
            return None
        except TimeoutError:
            wait = max(wait, 1) * 2
            LOGGER.debug(f'Timeout: Increasing wait to {wait} seconds.')
        status_code = response.status_code
        if status_code == 429:
            wait = max(wait, 1) * 2
            LOGGER.debug(f'Response 429: Increasing wait to {wait} seconds.')
        elif status_code == 503:
            LOGGER.error(f'The server at {url} reported that the service is unavailable, please try again later.')
            exit(1)
    return response
