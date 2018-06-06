"""
Common functionality for testssl-based checks.
"""
import os
import re
import tempfile
from pprint import pprint

from subprocess import call, check_output, DEVNULL

from django.conf import settings

from pprint import pprint


TESTSSL_PATH = os.path.join(
    settings.SCAN_TEST_BASEPATH, 'vendor/testssl.sh', 'testssl.sh')


def run_testssl(hostname: str, check_mx: bool, remote_host: str = None) -> bytes:
    """Test the specified hostname with testssl and return the raw json result."""
    # determine hostname
    if remote_host:
        out =  _remote_testssl(hostname, remote_host)
    else:
        out = _local_testssl(hostname, check_mx)

    # fix json syntax error
    out = re.sub(r'"Invocation.*?\n', '', out.decode(), 1).encode()

    return out


def parse_common_testssl(json: str, prefix: str):
    """Perform common parsing tasks on result JSONs."""
    result = {
        '{}_has_ssl'.format(prefix): True,  # otherwise an exception would have been thrown before
    }

    # Detect if cert is valid
    trust_cert = None
    trust_chain = None
    trust_pat = re.compile(r'(^trust$)|(.*? trust)')
    chain_pat = re.compile(r'.*?chain_of_trust$')
    # TODO If a server uses more than one certificate, this code will validate only the last one.
    for default in json['scanResult'][0]['serverDefaults']:
        if trust_pat.search(default['id']) is not None:
            trust_cert = default
        elif chain_pat.search(default['id']) is not None:
            trust_chain = default
        elif default["id"] == "issuer" and default["severity"] == "CRITICAL":
            trust_chain = default

    assert trust_cert is not None
    assert trust_chain is not None
    
    reason = ""
    trusted = True
    if not trust_cert['severity'] in ['OK', "INFO"]:
        reason += trust_cert['finding']
        trusted = False
    if not trust_chain['severity'] in ['OK', 'INFO']:
        reason += trust_chain['finding']
        trusted = False

    result['{}_cert_trusted'.format(prefix)] = trusted
    result['{}_cert_trusted_reason'.format(prefix)] = reason


    # pfs
    result['{}_pfs'.format(prefix)] = json['scanResult'][0]['pfs'][0]['severity'] == 'OK'

    # detect protocols
    pattern = re.compile(r'is (not )?offered')
    for p in json['scanResult'][0]['protocols']:
        if p['severity'] == "CRITICAL":
            # Hardcoded special case to grab a specific error
            # This is horrible style
            # TODO make less horrible
            pat = re.compile(r'higher version number')
            match = pat.search(p['finding'])
            result['{}_has_protocol_{}'.format(prefix, p['id'])] = match is None
            continue
        match = pattern.search(p['finding'])
        if not match:
            continue
        result['{}_has_protocol_{}'.format(prefix, p['id'])] = match.group(1) is None

    # Detect vulnerabilities
    result['{}_vulnerabilities'.format(prefix)] = {}
    for vuln in json['scanResult'][0]['vulnerabilities']:
        if vuln['severity'] != u"OK" and vuln['severity'] != u'INFO':
            result['{}_vulnerabilities'.format(prefix)][vuln['id']] = {
                'severity': vuln['severity'],
                'cve': vuln['cve'] if 'cve' in vuln.keys() else "",
                'finding': vuln['finding'],
            }
    
    # Detect ciphers
    # TODO Do we maybe want to get all cipher info, not only the bad ones?
    result['{}_ciphers'.format(prefix)] = {}
    for cipher in json['scanResult'][0]['ciphers']:
        if cipher['severity'] != u"OK" and cipher['severity'] != u'INFO':
            result['{}_ciphers'.format(prefix)][cipher['id']] = {
                'severity': cipher['severity'],
                'finding': cipher['finding'],
            }

    return result

def _remote_testssl(hostname: str, remote_host: str) -> bytes:
    """Run testssl over ssh."""
    return check_output([
        'ssh',
        remote_host,
        hostname,
    ])


def _local_testssl(hostname: str, check_mx: bool) -> bytes:
    result_file = tempfile.mktemp()

    args = [
        TESTSSL_PATH,
        '-p', # enable all checks for presence of SSLx.x and TLSx.x protocols
        '-h', # enable all checks for security-relevant HTTP headers
        '-s', # tests certain lists of cipher suites by strength
        '-f', # checks (perfect) forward secrecy settings
        '-U', # tests all (of the following) vulnerabilities (if applicable)
        '-S', # displays the server's default picks and certificate info, e.g.
              # used CA, trust chain, Sig Alg, DNS CAA, OCSP Stapling
        '-P', # displays the server's picks: protocol+cipher, e.g., cipher
              # order, security of negotiated protocol and cipher
        '--jsonfile-pretty', result_file,
        '--warnings=off',
        '--openssl-timeout', '10',
        '--sneaky', # use a harmless user agent instead of "SSL TESTER"
        '--fast', # skip some time-consuming checks
        '--ip', 'one', # do not scan all IPs returned by the DNS A query, but only the first one
    ]
    if check_mx:
        args.remove('-h')
        args.extend([
            '-t', 'smtp',  # test smtp
            '{}:25'.format(hostname),  # hostname on port 25
        ])
    else:
        args.append(hostname)

    call(args, stdout=DEVNULL, stderr=DEVNULL)

    # exception when file does not exist.
    with open(result_file, 'rb') as file:
        result = file.read()
    # delete json file.
    os.remove(result_file)

    # store raw scan result
    return result
