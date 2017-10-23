#!/usr/bin/python

import json
import logging
import sys
import traceback

import argparse
import os
import requests

from bart import Bart, BartError
from pybartlibs import HttpError, PyBartError
from pybartlibs import RestUser

from pycons3rt.logify import Logify

from requests.packages.urllib3.exceptions import InsecurePlatformWarning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.packages.urllib3.exceptions import SNIMissingWarning

# Set up logger name for this module
mod_logger = Logify.get_name() + '.pyBart.pybart_main'


def parse_user(file_path, project_name):
    """Create restUser from json file

    This method creates a user from file, using rest key for specific project

    :param file_path: (str) Full path to the user json file
    :param project_name: (str) Project name to get rest key for
    :return: restUser
    :raises PyBartError
    """
    log = logging.getLogger(mod_logger + '.parse_user')
    path = os.path.join(file_path, 'default_user.json')

    # Type checks on the arg
    if not isinstance(path, basestring):
        msg = 'file_path argument must be a string'
        log.error(msg)
        raise PyBartError(msg)

    if not isinstance(project_name, basestring):
        msg = 'file_path argument must be a string'
        log.error(msg)
        raise PyBartError(msg)

    # Ensure the file_path file exists
    if not os.path.isfile(path):
        msg = 'File not found: {f}'.format(f=path)
        log.error(msg)
        raise PyBartError(msg)

    with open(path, 'r') as f:
        data = json.load(f)

        username = data['name']
        token = None

        projects = data['projects']
        for project in projects:
            if project['name'] == project_name:
                token = project['rest_key']

    if token is None:
        msg = 'Project not found: {f}'.format(f=project_name)
        log.error(msg)
        raise PyBartError(msg)
    elif username is None:
        msg = 'Username not found: {f}'.format(f=username)
        log.error(msg)
        raise PyBartError(msg)
    else:
        return RestUser(username=username, token=token, project=project_name)


def main():

    # Remove once cert handling is more developed
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    requests.packages.urllib3.disable_warnings(InsecurePlatformWarning)
    requests.packages.urllib3.disable_warnings(SNIMissingWarning)

    log = logging.getLogger(mod_logger + '.main')

    try:
        parser = argparse.ArgumentParser(description='This Python module allows:')
        parser.add_argument('-u', '--url', help='Rest Api base URL', required=True)
        parser.add_argument('-d', '--base_dir', help='The base dir for json files', required=True)
        parser.add_argument('-p', '--project', help='The base project name', required=True)
        parser.add_argument('-m', '--mode', help='The mode to use', required=True)
        parser.add_argument('-v', '--virtrealm', help="The name of the virtualization realm to be allocated",
                            required=False, default='Springfield')
        parser.add_argument('-r', '--retries', help="The number of retry attempts to make for allocation",
                            required=False, default=5)
        parser.add_argument('-t', '--timeout', help="The number of seconds to wait for responses/results",
                            required=False, default=20)
        parser.add_argument('-q', '--queries', help='The number of times to query for allocated vr',
                            required=False, default=45)
        args = parser.parse_args()

        # TODO: exception handling and exit code
        pybart_config(url=args.url,
                      base_dir=args.base_dir,
                      project=args.project,
                      mode=args.mode,
                      virtrealm=args.virtrealm,
                      retries=args.retries,
                      timeout=args.timeout,
                      queries=args.queries)
    except (BartError, HttpError) as e:
        msg = 'There was a problem running rest client!\n{e}'.format(e=e)
        log.error(msg)
        traceback.print_exc()
        return 1
    return 0


def pybart_config(url, base_dir, project, mode, virtrealm='Springfield', retries=5, timeout=20, queries=45):

    # Remove once cert handling is more developed
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    requests.packages.urllib3.disable_warnings(InsecurePlatformWarning)
    requests.packages.urllib3.disable_warnings(SNIMissingWarning)

    log = logging.getLogger(mod_logger + '.config')

    try:
        json_base_dir = base_dir.strip()
        project_name = project.strip()

        user = parse_user(file_path=json_base_dir, project_name=project_name)

        # Build bart from required parameters
        my_bart = Bart(url.strip(), json_base_dir, user)

        # Set additional non-required fields
        my_bart.retries = retries
        my_bart.timeout = timeout
        my_bart.queries = queries
        my_bart.virtrealm = virtrealm.strip()

        log.info("Created rest user [ " + my_bart.user.username + ' ][ ' + my_bart.user.project_name + ' ][ ' +
                 my_bart.user.token + ' ]')

        mode = mode.lower().strip()

        log.info('Mode [ ' + mode + ' ] was requested')

        if mode == 'none':
            log.info('Done.')
        elif mode == 'register':
            my_bart.register_virtualization_realm()
        elif mode == 'allocate':
            my_bart.allocate_virtualization_realm()
        elif mode == 'deallocate':
            my_bart.deallocate_virtualization_realm()
        elif mode == 'unregister':
            my_bart.unregister_virtualization_realm()
        else:
            log.error("Mode " + mode + " is not supported")
            return 1
    except (BartError, HttpError) as e:
        msg = 'There was a problem running rest client!\n{e}'.format(e=e)
        log.error(msg)
        traceback.print_exc()
        return 1
    return 0

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
