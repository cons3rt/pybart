#!/usr/bin/python

import json
import logging
import time
import os
import sys
import shutil
import contextlib
import zipfile

import pycons3rt.deployment
from pycons3rt.bash import sed, mkdir_p
from pycons3rt.logify import Logify

from cons3rtclient import Cons3rtClient
from pybartlibs import RestUser, Cons3rtAssetStructureError, Cons3rtClientError, AssetZipCreationError

# Set up logger name for this module
mod_logger = Logify.get_name() + '.pyBart.bart'

# Bart config directory
bart_config_dir = os.path.join(os.path.expanduser('~'), '.pybart')

# Bart config file
bart_config_file = os.path.join(bart_config_dir, 'config.json')

# Files to ignore when creating assets
ignore_files = [
    '.DS_Store',
    '.gitignore',
    '._'
]

# Directories to ignore when creating assets
ignore_dirs = [
    '.git',
    '.svn',
    '.cons3rt'
]

# All items to ignore when creating assets
ignore_items = ignore_files + ignore_dirs


class BartError(Exception):
    """This class in an Exception type for handling errors with Bart
    """
    pass


class Bart:

    def __init__(self, url, base_dir=None, user=None, config_file=bart_config_file, project=None):
        self.cls_logger = mod_logger + '.Bart'
        self.user = user
        self.url_base = url
        self.base_dir = base_dir
        self.project = project
        self.retries = ''
        self.timeout = ''
        self.queries = ''
        self.virtrealm = ''
        self.config_file = config_file
        self.config_data = {}
        self.user_list = []
        if self.user is None:
            self.load_config()
        self.cons3rt_client = Cons3rtClient(base=url, user=self.user)

    def load_config(self):
        """Loads the default config file

        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.load_config')
        log.info('Loading pyBart configuration...')

        # Ensure the file_path file exists
        if not os.path.isfile(self.config_file):
            msg = 'Bart config file is required but not found: {f}'.format(f=self.config_file)
            raise BartError(msg)

        # Load the config file
        try:
            with open(self.config_file, 'r') as f:
                self.config_data = json.load(f)
        except(OSError, IOError):
            _, ex, trace = sys.exc_info()
            msg = 'Unable to read the Bart config file: {f}\n{e}'.format(f=self.config_file, e=str(ex))
            raise BartError, msg, trace
        else:
            log.debug('Loading config data from file: {f}'.format(f=self.config_file))

        # Attempt to find a username in the config data
        try:
            username = self.config_data['name']
        except KeyError:
            username = None

        # Attempt to find a cert_file_path in the config data
        try:
            cert_file_path = self.config_data['cert']
        except KeyError:
            cert_file_path = None
        else:
            # Ensure the cert_file_path points to an actual file
            if not os.path.isfile(cert_file_path):
                raise BartError('config.json provided a cert, but the cert file was not found: {f}'.format(
                    f=cert_file_path))
            log.info('Found certificate file: {f}'.format(f=cert_file_path))

        # Ensure that either a username or cert_file_path was found
        if username is None and cert_file_path is None:
            raise BartError('The pyBart config.json file must contain values for either name or cert')

        # Ensure at least one token is found
        try:
            project_token_list = self.config_data['projects']
        except KeyError:
            _, ex, trace = sys.exc_info()
            msg = 'Element [projects] is required but not found in the config data, at least 1 project token must ' \
                  'be configured\n{e}'.format(e=str(ex))
            raise BartError, msg, trace

        # Attempt to create a ReST user for each project in the list
        for project in project_token_list:
            try:
                token = project['rest_key']
                project_name = project['name']
            except KeyError:
                log.warn('Found an invalid project token, skipping: {p}'.format(p=str(project)))
                continue

            # Create a ReST User for the project/token pair
            log.debug('Found rest token for project {p}: {t}'.format(p=project, t=token))

            # Create a cert-based auth or username-based auth user depending on the config
            if cert_file_path:
                self.user_list.append(RestUser(token=token, project=project_name, cert_file_path=cert_file_path))
            elif username:
                self.user_list.append(RestUser(token=token, project=project_name, username=username))

        # Ensure that at least one valid project/token was found
        if len(self.user_list) < 1:
            raise BartError('A ReST API token was not found in config file: {f}'.format(f=self.config_file))

        log.info('Found {n} project/token pairs'.format(n=str(len(self.user_list))))

        # Select the first user to use as the default
        self.user = self.user_list[0]
        if self.project is not None:
            self.set_project_token(project_name=self.project)
        log.info('Set project to [{p}] and ReST API token: {t}'.format(p=self.user.project_name, t=self.user.token))

    def set_project_token(self, project_name):
        """Sets the project name and token to the specified project name.  This project name
        must already exist in config data

        :param project_name: (str) name of the project
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.set_project_token')

        # Ensure the project_name is a string
        if not isinstance(project_name, basestring):
            raise BartError('The arg project_name must be a string, found: {t}'.format(
                t=project_name.__class__.__name__))

        # Loop through the projects until the project matches
        found = False
        log.info('Attempting to set the project token pair for project: {p}'.format(p=project_name))
        for rest_user in self.user_list:
            log.debug('Checking if rest user matches project [{p}]: {u}'.format(p=project_name, u=str(rest_user)))
            if rest_user.project_name == project_name:
                log.info('Found matching rest user: {u}'.format(u=str(rest_user)))
                self.user = rest_user
                found = True
                break
        if found:
            log.info('Set project to [{p}] and ReST API token: {t}'.format(p=self.user.project_name, t=self.user.token))
        else:
            log.warn('Matching ReST User not found for project: {p}'.format(p=project_name))

    def set_project(self, desired_project_name):
        """Changes the project/token

        TODO remove, this is deprecated

        :param desired_project_name: (str) Name of the desired project
        :return: None
        :raises: BartError
        """
        self.set_project_token(project_name=desired_project_name)

    def get_asset_type(self, asset_type):
        """Translates the user-provided asset type to an actual ReST target

        :param asset_type: (str) provided asset type
        :return: (str) asset type ReSt target
        """
        log = logging.getLogger(self.cls_logger + '.get_asset_type')

        # Determine the target based on asset_type
        target = ''
        if 'scenario' in asset_type.lower():
            target = 'scenarios'
        elif 'deployment' in asset_type.lower():
            target = 'deployments'
        elif 'software' in asset_type.lower():
            target = 'software'
        elif 'system' in asset_type.lower():
            target = 'systems'
        elif 'test' in asset_type.lower():
            target = 'testassets'
        else:
            log.warn('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))
        return target

    def register_cloud_from_json(self, json_file):
        """Attempts to register a Cloud using the provided JSON
        file as the payload

        :param json_file: (str) path to the JSON file
        :return: (int) Cloud ID
        :raises BartError
        """
        log = logging.getLogger(self.cls_logger + '.register_cloud_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to register the Cloud
        try:
            cloud_id = self.cons3rt_client.register_cloud(cloud_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to register a Cloud using JSON file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully registered Cloud ID: {c}'.format(c=str(cloud_id)))
        return cloud_id

    def create_team_from_json(self, json_file):
        """Attempts to create a Team using the provided JSON
        file as the payload

        :param json_file: (str) path to the JSON file
        :return: (int) Team ID
        :raises BartError
        """
        log = logging.getLogger(self.cls_logger + '.create_team_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to create the team
        try:
            team_id = self.cons3rt_client.create_team(team_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to create a Team using JSON file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully created Team ID: {c}'.format(c=str(team_id)))
        return team_id

    def register_virtualization_realm_to_cloud_from_json(self, cloud_id, json_file):
        """Attempts to register a virtualization realm using
        the provided JSON file as the payload

        :param cloud_id: (int) Cloud ID to register the VR under
        :param json_file: (str) path to JSON file
        :return: (int) Virtualization Realm ID
        :raises BartError
        """
        log = logging.getLogger(self.cls_logger + '.register_virtualization_realm_to_cloud_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise BartError(msg)

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError:
                msg = 'The cloud_id arg must be an int'
                raise BartError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to register the virtualization realm to the Cloud ID
        try:
            vr_id = self.cons3rt_client.register_virtualization_realm(
                cloud_id=cloud_id,
                virtualization_realm_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to register virtualization realm to Cloud ID {c} from file: {f}\n{e}'.format(
                n=ex.__class__.__name__, c=cloud_id, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Registered new Virtualization Realm ID {v} to Cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        return vr_id

    def allocate_virtualization_realm_to_cloud_from_json(self, cloud_id, json_file):
        """Attempts to allocate a virtualization realm using
        the provided JSON file as the payload

        :param cloud_id: (int) Cloud ID to allocate the VR under
        :param json_file: (str) path to JSON file
        :return: (int) Virtualization Realm ID
        :raises BartError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_virtualization_realm_to_cloud_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise BartError(msg)

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError:
                msg = 'The cloud_id arg must be an int'
                raise BartError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to register the virtualization realm to the Cloud ID
        try:
            vr_id = self.cons3rt_client.allocate_virtualization_realm(
                cloud_id=cloud_id,
                allocate_virtualization_realm_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to allocate virtualization realm to Cloud ID {c} from file: {f}'.format(
                n=ex.__class__.__name__, c=cloud_id, f=json_file)
            raise BartError, msg, trace
        log.info('Allocated new Virtualization Realm ID {v} to Cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        return vr_id

    def list_projects(self):
        """Query CONS3RT to return a list of projects for the current user

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_projects')
        log.debug('Attempting to list projects for user: {u}'.format(u=self.user.username))
        try:
            projects = self.cons3rt_client.list_projects()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of projects\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return projects

    def list_expanded_projects(self):
        """Query CONS3RT to return a list of projects the current user is not a member of

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_expanded_projects')
        log.debug('Attempting to list non-member projects for user: {u}'.format(u=self.user.username))
        try:
            projects = self.cons3rt_client.list_expanded_projects()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of projects\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return projects

    def list_all_projects(self):
        """Query CONS3RT to return a list of all projects on the site

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_all_projects')
        log.debug('Attempting to list all projects...')
        try:
            member_projects = self.cons3rt_client.list_projects()
            non_member_projects = self.cons3rt_client.list_expanded_projects()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of projects\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return member_projects + non_member_projects

    def get_project_details(self, project_id):
        """Returns details for the specified project ID

        :param (int) project_id: ID of the project to query
        :return: (dict) details for the project ID
        """
        log = logging.getLogger(self.cls_logger + '.get_project_details')

        # Ensure the vr_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise BartError(msg)

        log.debug('Attempting query project ID {i}'.format(i=str(project_id)))
        try:
            project_details = self.cons3rt_client.get_project_details(project_id=project_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for details on project: {i}\n{e}'.format(i=str(project_id), e=str(ex))
            raise BartError, msg, trace
        return project_details

    def get_project_id(self, project_name):
        """Given a project name, return a list of IDs with that name

        :param project_name: (str) name of the project
        :return: (list) of project IDs (int)
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.get_project_id')

        if not isinstance(project_name, basestring):
            raise BartError('Expected project_name arg to be a string, found: {t}'.format(
                t=project_name.__class__.__name__)
            )

        project_id_list = []

        # List all projects
        log.debug('Getting a list of all projects...')
        try:
            projects = self.list_all_projects()
        except BartError:
            _, ex, trace = sys.exc_info()
            msg = 'BartError: There was a problem listing all projects\n{e}'.format(e=str(ex))
            raise BartError, msg, trace

        # Look for project IDs with matching names
        log.debug('Looking for projects with name: {n}'.format(n=project_name))
        for project in projects:
            if project['name'] == project_name:
                project_id_list.append(project['id'])

        # Raise an error if the project was not found
        if len(project_id_list) < 1:
            raise BartError('Project not found: {f}'.format(f=project_name))

        # Return the list of IDs
        return project_id_list

    def list_projects_in_virtualization_realm(self, vr_id):
        """Queries CONS3RT for a list of projects in the virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: (list) of projects
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_projects_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise BartError(msg)

        log.debug('Attempting to list projects in virtualization realm ID: {i}'.format(i=str(vr_id)))
        try:
            projects = self.cons3rt_client.list_projects_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of projects in virtualization realm ID: {i}\n{e}'.format(
                i=str(vr_id), e=str(ex))
            raise BartError, msg, trace
        return projects

    def list_clouds(self):
        """Query CONS3RT to return a list of the currently configured Clouds

        :return: (list) of Cloud Info
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_clouds')
        log.info('Attempting to list clouds...')
        try:
            clouds = self.cons3rt_client.list_clouds()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of Clouds\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return clouds

    def list_teams(self):
        """Query CONS3RT to return a list of Teams

        :return: (list) of Team Info
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_teams')
        log.info('Attempting to list teams...')
        try:
            teams = self.cons3rt_client.list_teams()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of Teams\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return teams

    def get_team_details(self, team_id):
        """Returns details for the specified team ID

        :param (int) team_id: ID of the team to query
        :return: (dict) details for the team ID
        """
        log = logging.getLogger(self.cls_logger + '.get_team_details')

        # Ensure the vr_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise BartError(msg)

        log.debug('Attempting query team ID {i}'.format(i=str(team_id)))
        try:
            team_details = self.cons3rt_client.get_team_details(team_id=team_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for details on team: {i}\n{e}'.format(i=str(team_id), e=str(ex))
            raise BartError, msg, trace
        return team_details

    def list_scenarios(self):
        """Query CONS3RT to return a list of Scenarios

        :return: (list) of Scenario Info
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_scenarios')
        log.info('Attempting to get a list of scenarios...')
        try:
            scenarios = self.cons3rt_client.list_scenarios()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of scenarios\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return scenarios

    def list_deployments(self):
        """Query CONS3RT to return a list of Deployments

        :return: (list) of Deployments Info
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployments')
        log.info('Attempting to get a list of deployments...')
        try:
            deployments = self.cons3rt_client.list_deployments()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of deployments\n{e}'.format(e=str(ex))
            raise BartError, msg, trace
        return deployments

    def list_deployment_runs_in_virtualization_realm(self, vr_id, search_type='SEARCH_ALL'):
        """Query CONS3RT to return a list of deployment runs in a virtualization realm

        :param: vr_id: (int) virtualization realm ID
        :param: search_type (str) the run status to filter the search on
        :return: (list) of deployment runs
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise BartError(msg)

        # Ensure status is valid
        if not isinstance(search_type, basestring):
            raise BartError('Arg search_type must be a string, found type: {t}'.format(
                t=search_type.__class__.__name__))

        valid_search_type = ['SEARCH_ACTIVE', 'SEARCH_ALL', 'SEARCH_AVAILABLE', 'SEARCH_COMPOSING',
                             'SEARCH_DECOMPOSING', 'SEARCH_INACTIVE', 'SEARCH_PROCESSING', 'SEARCH_SCHEDULED',
                             'SEARCH_TESTING', 'SEARCH_SCHEDULED_AND_ACTIVE']

        search_type = search_type.upper()
        if search_type not in valid_search_type:
            raise BartError('Arg status provided is not valid, must be one of: {s}'.format(s=', '.join(search_type)))

        # Attempt to get a list of deployment runs
        log.info('Attempting to get a list of deployment runs with search_type {s} in '
                 'virtualization realm ID: {i}'.format(i=str(vr_id), s=search_type))
        try:
            drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type=search_type)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT VR ID {i} for a list of deployment runs\n{e}'.format(
                i=str(vr_id), e=str(ex))
            raise BartError, msg, trace
        log.info('Found {n} runs in VR ID: {i}'.format(i=str(vr_id), n=str(len(drs))))
        return drs

    def retrieve_deployment_run_details(self, dr_id):
        """Query CONS3RT to return details of a deployment run

        :param: (int) deployment run ID
        :return: (dict) of deployment run detailed info
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_deployment_run_details')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise BartError(msg)

        # Query for DR details
        log.info('Attempting to retrieve details for deployment run ID: {i}'.format(i=str(dr_id)))
        try:
            dr_details = self.cons3rt_client.retrieve_deployment_run_details(dr_id=dr_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a details of deployment run ID: {i}\n{e}'.format(
                i=str(dr_id), e=str(ex))
            raise BartError, msg, trace
        return dr_details

    def list_virtualization_realms_for_cloud(self, cloud_id):
        """Query CONS3RT to return a list of VRs for a specified Cloud ID

        :param cloud_id: (int) Cloud ID
        :return: (list) of Virtualization Realm data
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms_for_cloud')
        log.info('Attempting to list virtualization realms for cloud ID: {i}'.format(i=cloud_id))
        try:
            vrs = self.cons3rt_client.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms for Cloud ID: {c}\n{e}'.format(
                c=cloud_id, e=str(ex))
            raise BartError, msg, trace
        return vrs

    def add_cloud_admin(self, cloud_id, username=None):
        """Adds a users as a Cloud Admin

        :param username: (str) Username
        :param cloud_id: (int) Cloud ID
        :return: None
        :raises: BartError, ValueError
        """
        log = logging.getLogger(self.cls_logger + '.add_cloud_admin')
        if username is None:
            username = self.user.username
        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError:
                msg = 'The cloud_id arg must be an int'
                raise BartError(msg)
        try:
            self.cons3rt_client.add_cloud_admin(cloud_id=cloud_id, username=self.user.username)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to add Cloud Admin {u} to Cloud: {c}\n{e}'.format(u=username, c=cloud_id, e=str(ex))
            raise BartError, msg, trace
        else:
            log.info('Added Cloud Admin {u} to Cloud: {c}'.format(u=username, c=cloud_id))

    def register_virtualization_realm(self):
        """Registers a new Virt Realm

        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.register_virtualization_realm')
        dep = pycons3rt.deployment.Deployment()

        key_prop_name = dep.get_property('AWS_ACCESS_KEY_ID')
        if key_prop_name is None:
            msg = 'Property not found: {f}'.format(f='AWS_ACCESS_KEY_ID')
            raise BartError(msg)
        aws_key_id = dep.get_value(key_prop_name)

        secret_prop_name = dep.get_property('AWS_SECRET_ACCESS_KEY')
        if secret_prop_name is None:
            msg = 'Property not found: {f}'.format(f='AWS_SECRET_ACCESS_KEY')
            raise BartError(msg)
        aws_secret_key = dep.get_value(secret_prop_name)

        if aws_key_id is None or aws_secret_key is None:
            msg = 'Either {f} or {e} was not defined'.format(f='AWS_ACCESS_KEY_ID', e='AWS_SECRET_ACCESS_KEY')
            raise BartError(msg)

        log.info("Aws access key id : " + aws_key_id)
        log.info("Aws secret key : " + aws_secret_key)

        sed(file_path=self.base_dir + '/' + 'cloud.json', pattern='REPLACE_AWS_ACCESS_KEY_ID', replace_str=aws_key_id)
        sed(file_path=self.base_dir + '/' + 'cloud.json', pattern='REPLACE_AWS_SECRET_ACCESS_KEY',
            replace_str=aws_secret_key)

        cloud_id = self.cons3rt_client.register_cloud(cloud_file=self.base_dir + '/' + 'cloud.json')
        log.info('Cloud id: ' + str(cloud_id))

        self.cons3rt_client.add_cloud_admin(cloud_id=cloud_id, username=self.user.username)
        log.info('Admin ' + self.user.username + ' added to cloud ' + str(cloud_id))

        # Attempt to get the list of project IDs
        try:
            project_ids = self.get_project_id(project_name=self.user.project_name)
        except BartError:
            _, ex, trace = sys.exc_info()
            msg = 'There was a problem finding a project ID for project: {n}'.format(n=self.user.project_name)
            raise BartError, msg, trace

        if len(project_ids) != 1:
            raise BartError('Found more than one project ID matching name [{n}]: {i}'.format(
                n=self.user.project_name, i=','.join(project_ids)))

        project_id = project_ids[0]
        log.info('Project id of default project: ' + str(project_id))

        vr_name = self.virtrealm

        log.info("Aws access key id : " + aws_key_id)
        log.info("Aws secret key : " + aws_secret_key)
        log.info("Virtualization realm name : " + str(vr_name))

        sed(file_path=self.base_dir + '/' + 'virtualization_realm.json', pattern='REPLACE_AWS_ACCESS_KEY_ID',
            replace_str=aws_key_id)
        sed(file_path=self.base_dir + '/' + 'virtualization_realm.json', pattern='REPLACE_AWS_SECRET_ACCESS_KEY',
            replace_str=aws_secret_key)
        sed(file_path=self.base_dir + '/' + 'virtualization_realm.json', pattern='REPLACE_VIRTUALIZATION_REALM_NAME',
            replace_str=vr_name)

        log.info('Registering virtualization realm: ' + str(vr_name))

        vr_id = self.cons3rt_client.register_virtualization_realm(
            cloud_id=cloud_id, virtualization_realm_file=self.base_dir + '/' + 'virtualization_realm.json')
        log.info('Virtualization Realm id: ' + str(vr_id))

        self.cons3rt_client.add_virtualization_realm_admin(vr_id=vr_id, username=self.user.username)
        log.info('Admin ' + self.user.username + ' added to vr ' + str(vr_id))

        self.cons3rt_client.add_project_to_virtualization_realm(vr_id=vr_id, project_id=project_id)
        log.info('Project ' + str(project_id) + ' added to vr ' + str(vr_id))

        log.info('Cloud and Virtualization Realm populate complete')

    def allocate_virtualization_realm(self):
        """Allocates a new Virt Realm

        :return:
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.default_populate')
        dep = pycons3rt.deployment.Deployment()

        key_prop_name = dep.get_property('AWS_ACCESS_KEY_ID')
        if key_prop_name is None:
            msg = 'Property not found: {f}'.format(f='AWS_ACCESS_KEY_ID')
            raise BartError(msg)
        aws_key_id = dep.get_value(key_prop_name)

        secret_prop_name = dep.get_property('AWS_SECRET_ACCESS_KEY')
        if secret_prop_name is None:
            msg = 'Property not found: {f}'.format(f='AWS_SECRET_ACCESS_KEY')
            raise BartError(msg)
        aws_secret_key = dep.get_value(secret_prop_name)

        if aws_key_id is None or aws_secret_key is None:
            msg = 'Either {f} or {e} was not defined'.format(f='AWS_ACCESS_KEY_ID', e='AWS_SECRET_ACCESS_KEY')
            raise BartError(msg)

        log.info("Aws access key id : " + aws_key_id)
        log.info("Aws secret key : " + aws_secret_key)

        sed(file_path=self.base_dir + '/' + 'cloud.json', pattern='REPLACE_AWS_ACCESS_KEY_ID', replace_str=aws_key_id)
        sed(file_path=self.base_dir + '/' + 'cloud.json', pattern='REPLACE_AWS_SECRET_ACCESS_KEY',
            replace_str=aws_secret_key)

        cloud_id = self.cons3rt_client.register_cloud(cloud_file=self.base_dir + '/' + 'cloud.json')
        log.info('Cloud id: ' + str(cloud_id))

        self.cons3rt_client.add_cloud_admin(cloud_id=cloud_id, username=self.user.username)
        log.info('Admin ' + self.user.username + ' added to cloud ' + str(cloud_id))

        project_id = self.get_project_id(project_name=self.user.project_name)
        log.info('Project id of default project: ' + str(project_id))

        vr_id = None
        vr_name = self.virtrealm

        log.info('Attempting to allocate virtualization realm: ' + str(vr_name))

        retry_count = 0
        while retry_count < self.retries:
            # TODO THIS IS NOW BROKEN
            allocated = self.cons3rt_client.allocate_virtualization_realm(
                cloud_id=cloud_id,
                allocate_virtualization_realm_file=None
            )

            if retry_count == 0:
                log.info('Virtualization Realm allocation started: ' + str(allocated))
            else:
                log.info('Virtualization Realm allocation attempt ' + str(retry_count) + ' started: ' + str(allocated))

            if allocated.lower() == 'true':
                # Start retry and detection logic
                max_count = int(self.queries)
                retry_sec = int(self.timeout)
                log.info('Starting to check for allocated virtualization realm: ' + vr_name +
                         '. An attempt will be made every (' + str(retry_sec) + ') Seconds, up to (' +
                         str(max_count) + ') times.')

                for count in range(0, max_count):
                    log.info('-- This is query: {c}'.format(c=count))
                    # check for vr existence, if none sleep
                    vr_id = self.cons3rt_client.get_virtualization_realm_id(cloud_id=cloud_id, vr_name=vr_name)
                    if vr_id is None:
                        time.sleep(retry_sec)
                    else:
                        break

                if vr_id is None:
                    log.info('-- Allocated virtualization realm ' + vr_name + ' still not found after ' +
                             str(max_count) + ' attempts. Re-attemping allocation.')
                    retry_count += 1
                else:
                    break

            else:
                msg = 'Attempt to allocate virtualization realm ' + str(vr_name) + ' in cloud ' + str(cloud_id) + \
                      'returned ' + str(allocated)
                raise BartError(msg)

        if vr_id is None:
            msg = '-- Virtualization realm ' + vr_name + ' failed to be allocated after ' + str(self.retries) + \
                  ' attempts.'
            raise BartError(msg)
        else:
            log.info('Allocated virtualization realm id ' + str(vr_id))

        # This needs the vr to be allocated and have an id
        self.cons3rt_client.add_virtualization_realm_admin(vr_id=vr_id, username=self.user.username)
        log.info('Admin ' + self.user.username + ' added to vr ' + str(vr_id))

        self.cons3rt_client.add_project_to_virtualization_realm(vr_id=vr_id, project_id=project_id)
        log.info('Project ' + str(project_id) + ' added to vr ' + str(vr_id))

        log.info('Cloud and Virtualization Realm populate complete')

    def deallocate_virtualization_realm(self):
        """Deallocates a Virt Realm

        :return:
        :raises:
        """

        log = logging.getLogger(self.cls_logger + '.deallocate_virtualization_realm')

        cloud_file = self.base_dir + '/' + 'cloud.json'

        log.info('Using cloud file [ ' + cloud_file + ' ]')

        with open(cloud_file, 'r') as f:
            cloud = json.load(f)
        cloud_name = cloud['name']

        log.info('Determined cloud name [ ' + cloud_name + ' ] from file.')

        cloud_id = self.cons3rt_client.get_cloud_id(cloud_name=cloud_name)

        if cloud_id is None:
            log.warn('Unable to find a Cloud ID from name: [ ' + cloud_name + ' ], nothing to do.')
            return

        log.info('Determined cloud id [ ' + str(cloud_id) + ' ] for cloud ' + cloud_name)

        vr_id = self.cons3rt_client.get_virtualization_realm_id(cloud_id=cloud_id, vr_name=self.virtrealm)

        if vr_id is None:
            log.warn('Unable to find a Virtualization Realm ID from name: [ ' + self.virtrealm + ' ], nothing to do.')
            return

        log.info('Determined virtualization realm id [ ' + str(vr_id) + ' ] for virtualization realm ' + self.virtrealm)

        log.info('Deactivating virtualization realm [ ' + str(vr_id) + ' ]')

        self.cons3rt_client.deactivate_virtualization_realm(vr_id=vr_id)

        log.info('Listing all projects from virtualization realm [ ' + str(vr_id) + ' ]')

        projects = self.cons3rt_client.list_projects_in_virtualization_realm(vr_id=vr_id)
        if not projects:
            log.info('    No projects found.')
        else:
            for project in projects:
                project_id = project['id']
                log.info('    Found project [ ' + str(project_id) + ' ]. Removing....')
                self.cons3rt_client.remove_project_from_virtualization_realm(vr_id=vr_id, project_id=project_id)

        log.info('Listing all active deployment runs in virtualization realm [ ' + str(vr_id) + ' ]')

        drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ACTIVE')
        if not drs:
            log.info('    No Active deployment runs found')
        else:
            for dr in drs:
                dr_id = dr['id']
                log.info('    Found deployment run [ ' + str(dr_id) + ' ]. Releasing...')
                self.cons3rt_client.release_deployment_run(dr_id=dr_id)

            log.info('Waiting until all deployment runs have been released.')
            not_done = True
            while not_done:
                drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(
                    vr_id=vr_id, search_type='SEARCH_ACTIVE')
                if not drs:
                    not_done = True
                    log.info('    Deployment runs in active state(s) still exist in virtualization realm [ ' +
                             str(vr_id) + ' ] waiting...')
                    time.sleep(20)
                else:
                    not_done = False

            log.info('All deployment runs have been released.')

        log.info('Deleting deployment runs.')

        drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ALL')
        if not drs:
            log.info('    No Deployment runs found')
        else:
            for dr in drs:
                dr_id = dr['id']
                log.info('    Deleting deployment run [ ' + str(dr_id) + ' ].')
                self.cons3rt_client.delete_deployment_run(dr_id=dr_id)

            log.info('All found deployment runs deleted.')

        log.info('All prerequisite steps have been taken, deallocating virtualization realm [ ' + str(vr_id) + ' ]')

        self.cons3rt_client.deallocate_virtualization_realm(cloud_id=cloud_id, vr_id=vr_id)

        log.info('Successfully deallocated virtualization realm [ ' + str(vr_id) + ' ]')

    def unregister_virtualization_realm(self):
        """Unregisters a Virt Realm

        :return:
        :raises:
        """

        log = logging.getLogger(self.cls_logger + '.unregister_virtualization_realm')

        cloud_file = self.base_dir + '/' + 'cloud.json'

        log.info('Using cloud file [ ' + cloud_file + ' ]')

        with open(cloud_file, 'r') as f:
            cloud = json.load(f)
        cloud_name = cloud['name']

        log.info('Determined cloud name [ ' + cloud_name + ' ] from file.')

        cloud_id = self.cons3rt_client.get_cloud_id(cloud_name=cloud_name)

        if cloud_id is None:
            log.warn('Unable to find a Cloud ID from name: [ ' + cloud_name + ' ], nothing to do.')
            return

        log.info('Determined cloud id [ ' + str(cloud_id) + ' ] for cloud ' + cloud_name)

        vr_id = self.cons3rt_client.get_virtualization_realm_id(cloud_id=cloud_id, vr_name=self.virtrealm)

        if vr_id is None:
            log.warn('Unable to find a Virtualization Realm ID from name: [ ' + self.virtrealm + ' ], nothing to do.')
            return

        log.info('Determined virtualization realm id [ ' + str(vr_id) + ' ] for virtualization realm ' + self.virtrealm)

        log.info('Deactivating virtualization realm [ ' + str(vr_id) + ' ]')

        self.cons3rt_client.deactivate_virtualization_realm(vr_id=vr_id)

        log.info('Listing all projects from virtualization realm [ ' + str(vr_id) + ' ]')

        projects = self.cons3rt_client.list_projects_in_virtualization_realm(vr_id=vr_id)
        if not projects:
            log.info('    No projects found.')
        else:
            for project in projects:
                project_id = project['id']
                log.info('    Found project [ ' + str(project_id) + ' ]. Removing....')
                self.cons3rt_client.remove_project_from_virtualization_realm(vr_id=vr_id, project_id=project_id)

        log.info('Listing all active deployment runs in virtualization realm [ ' + str(vr_id) + ' ]')

        drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ACTIVE')
        if not drs:
            log.info('    No Active deployment runs found')
        else:
            for dr in drs:
                dr_id = dr['id']
                log.info('    Found deployment run [ ' + str(dr_id) + ' ]. Releasing...')
                self.cons3rt_client.release_deployment_run(dr_id=dr_id)

            log.info('Waiting until all deployment runs have been released.')
            not_done = True
            while not_done:
                drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(
                    vr_id=vr_id, search_type='SEARCH_ACTIVE')
                if not drs:
                    not_done = True
                    log.info('    Deployment runs in active state(s) still exist in virtualization realm [ ' +
                             str(vr_id) + ' ] waiting...')
                    time.sleep(20)
                else:
                    not_done = False

            log.info('All deployment runs have been released.')

        log.info('Deleting deployment runs.')

        drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ALL')
        if not drs:
            log.info('    No Deployment runs found')
        else:
            for dr in drs:
                dr_id = dr['id']
                log.info('    Deleting deployment run [ ' + str(dr_id) + ' ].')
                self.cons3rt_client.delete_deployment_run(dr_id=dr_id)

            log.info('All found deployment runs deleted.')

        log.info('Successfully purged virtualization realm [ ' + str(vr_id) + ' ]')

    def delete_asset(self, asset_type, asset_id):
        """Deletes the asset based on a provided asset type

        :param asset_type: (str) asset type
        :param asset_id: (int) asset ID
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.delete_asset')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError:
                msg = 'asset_id arg must be an Integer, found: {t}'.format(t=asset_id.__class__.__name__)
                raise BartError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_type, basestring):
            msg = 'The asset_type arg must be a string, found {t}'.format(t=asset_type.__class__.__name__)
            raise BartError(msg)

        # Determine the target based on asset_type
        target = self.get_asset_type(asset_type=asset_type)
        if target == '':
            raise BartError('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))

        # Ensure the target is valid
        valid_targets = ['scenarios', 'deployments', 'systems', 'software', 'clouds', 'teams', 'projects']
        if target not in valid_targets:
            msg = 'Provided asset_type does not match a valid asset type that can be deleted.  Valid asset types ' \
                  'are: {t}'.format(t=','.join(valid_targets))
            raise BartError(msg)

        # Attempt to delete the target
        try:
            self.cons3rt_client.delete_asset(asset_id=asset_id, asset_type=target)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to delete {t} with asset ID: {i}\n{e}'.format(
                n=ex.__class__.__name__, i=str(asset_id), t=target, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully deleted {t} asset ID: {i}'.format(i=str(asset_id), t=target))

    def update_asset_content(self, asset_id, asset_zip_file):
        """Updates the asset content for the provided asset_id using the asset_zip_file

        :param asset_id: (int) ID of the asset to update
        :param asset_zip_file: (str) path to the asset zip file
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_content')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError:
                msg = 'asset_id arg must be an Integer'
                raise ValueError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_zip_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the asset_zip_file file exists
        if not os.path.isfile(asset_zip_file):
            msg = 'Asset zip file file not found: {f}'.format(f=asset_zip_file)
            raise OSError(msg)

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_content(asset_id=asset_id, asset_zip_file=asset_zip_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to update asset ID {i} using asset zip file: {f}\n{e}'.format(
                n=ex.__class__.__name__, i=str(asset_id), f=asset_zip_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully updated Asset ID: {i}'.format(i=str(asset_id)))

    def update_asset_state(self, asset_type, asset_id, state):
        """Updates the asset state

        :param asset_type: (str) asset type (scenario, deployment, system, etc)
        :param asset_id: (int) asset ID to update
        :param state: (str) desired state
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_state')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError:
                msg = 'asset_id arg must be an Integer'
                raise BartError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_type, basestring):
            msg = 'The asset_type arg must be a string, found {t}'.format(t=asset_type.__class__.__name__)
            raise BartError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(state, basestring):
            msg = 'The state arg must be a string, found {t}'.format(t=state.__class__.__name__)
            raise BartError(msg)

        # Determine the target based on asset_type
        target = self.get_asset_type(asset_type=asset_type)
        if target == '':
            raise BartError('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))

        # Ensure state is valid
        valid_states = ['DEVELOPMENT', 'PUBLISHED', 'CERTIFIED', 'DEPRECATED', 'OFFLINE']
        state = state.upper().strip()
        if state not in valid_states:
            raise BartError('Provided state is not valid: {s}, must be one of: {v}'.format(s=state, v=valid_states))

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_state(asset_id=asset_id, state=state, asset_type=target)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to update the state for asset ID: {i}\n{e}'.format(
                n=ex.__class__.__name__, i=str(asset_id), e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully updated state for Asset ID {i} to: {s}'.format(i=str(asset_id), s=state))

    def update_asset_visibility(self, asset_type, asset_id, visibility):
        """Updates the asset visibilty

        :param asset_type: (str) asset type (scenario, deployment, system, etc)
        :param asset_id: (int) asset ID to update
        :param visibility: (str) desired asset visibilty
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_visibility')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError:
                msg = 'asset_id arg must be an Integer'
                raise BartError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_type, basestring):
            msg = 'The asset_type arg must be a string, found {t}'.format(t=asset_type.__class__.__name__)
            raise BartError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(visibility, basestring):
            msg = 'The visibility arg must be a string, found {t}'.format(t=visibility.__class__.__name__)
            raise BartError(msg)

        # Determine the target based on asset_type
        target = self.get_asset_type(asset_type=asset_type)
        if target == '':
            raise BartError('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))

        # Valid values for visibility
        valid_visibility = ['OWNER', 'OWNING_PROJECT', 'TRUSTED_PROJECTS', 'COMMUNITY']

        # Ensure visibility is cvalid
        visibility = visibility.upper().strip()
        if visibility not in valid_visibility:
            raise BartError('Provided visibility is not valid: {s}, must be one of: {v}'.format(
                s=visibility, v=valid_visibility))

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_visibility(asset_id=asset_id, visibility=visibility, asset_type=target)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to update the visibility for asset ID: {i}\n{e}'.format(
                n=ex.__class__.__name__, i=str(asset_id), e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully updated visibility for Asset ID {i} to: {s}'.format(i=str(asset_id), s=visibility))

    def import_asset(self, asset_zip_file):
        """

        :param asset_zip_file:
        :return:
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.import_asset')

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_zip_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the asset_zip_file file exists
        if not os.path.isfile(asset_zip_file):
            msg = 'Asset zip file file not found: {f}'.format(f=asset_zip_file)
            raise OSError(msg)

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.import_asset(asset_zip_file=asset_zip_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to import asset using asset zip file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=asset_zip_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully imported asset from file: {f}'.format(f=asset_zip_file))

    def enable_remote_access(self, virtualization_realm_id, size=None):
        """Enables Remote Access for a specific virtualization realm, and uses SMALL
        as the default size if none is provided.

        :param virtualization_realm_id: (int) ID of the virtualization
        :param size: (str) small, medium, or large
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.enable_remote_access')

        # Ensure the virtualization_realm_id is an int
        if not isinstance(virtualization_realm_id, int):
            try:
                virtualization_realm_id = int(virtualization_realm_id)
            except ValueError:
                raise ValueError('virtualization_realm_id arg must be an Integer')

        # Use small as the default size
        if size is None:
            size = 'SMALL'

        # Ensure size is a string
        if not isinstance(size, basestring):
            raise ValueError('The size arg must be a string')

        # Acceptable sizes
        size_options = ['SMALL', 'MEDIUM', 'LARGE']
        size = size.upper()
        if size not in size_options:
            raise ValueError('The size arg must be set to SMALL, MEDIUM, or LARGE')

        # Attempt to enable remote access
        log.info('Attempting to enable remote access in virtualization realm ID {i} with size: {s}'.format(
            i=virtualization_realm_id, s=size))
        try:
            self.cons3rt_client.enable_remote_access(virtualization_realm_id=virtualization_realm_id, size=size)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: There was a problem enabling remote access in virtualization realm ID: {i} with size: ' \
                  '{s}\n{e}'.format(n=ex.__class__.__name__, i=virtualization_realm_id, s=size, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully enabled remote access in virtualization realm: {i}, with size: {s}'.format(
            i=virtualization_realm_id, s=size))

    def retrieve_all_users(self):
        """Retrieve all users from the CONS3RT site

        :return: (list) containing all site users
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.query_all_users')
        log.info('Attempting to query CONS3RT to retrieve all users...')
        try:
            users = self.cons3rt_client.retrieve_all_users()
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: There was a problem querying for all users\n{e}'.format(n=ex.__class__.__name__, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully enabled retrieved all site users')
        return users

    def create_user_from_json(self, json_file):
        """Creates a single CONS3RT user using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.create_user_from_json')
        log.info('Attempting to query CONS3RT to create a user from JSON file...')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to create the team
        try:
            self.cons3rt_client.create_user(user_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to create a User using JSON file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully created User from file: {f}'.format(f=json_file))

    def add_user_to_project(self, username, project_id):
        """Add the username to the specified project ID

        :param username: (str) CONS3RT username to add to the project
        :param project_id: (int) ID of the project
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.add_user_to_project')

        # Ensure the username arg is a string
        if not isinstance(username, basestring):
            msg = 'The username arg must be a string'
            raise BartError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise BartError(msg)

        # Attempt to add the user to the project
        try:
            self.cons3rt_client.add_user_to_project(username=username, project_id=project_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to add username {u} to project ID: {i}\n{e}'.format(
                n=ex.__class__.__name__, u=username, i=str(project_id), e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully added username {u} to project ID: {i}'.format(i=str(project_id), u=username))

    def create_scenario_from_json(self, json_file):
        """Creates a scenario using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: (int) Scenario ID
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.create_scenario_from_json')
        log.info('Attempting to query CONS3RT to create a scenario from JSON file...')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to create the team
        try:
            scenario_id = self.cons3rt_client.create_scenario(scenario_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to create a scenario using JSON file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully created scenario ID {i} from file: {f}'.format(i=scenario_id, f=json_file))
        return scenario_id

    def create_deployment_from_json(self, json_file):
        """Creates a deployment using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: (int) Deployment ID
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.create_deployment_from_json')
        log.info('Attempting to query CONS3RT to create a deployment from JSON file...')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string, found: {t}'.format(t=json_file.__class__.__name__)
            raise BartError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise BartError(msg)

        # Attempt to create the team
        try:
            deployment_id = self.cons3rt_client.create_deployment(deployment_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to create a deployment using JSON file: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully created deployment ID {i} from file: {f}'.format(i=deployment_id, f=json_file))
        return deployment_id

    def release_deployment_run(self, dr_id):
        """Release a deployment run by ID

        :param: dr_id: (int) deployment run ID
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.release_deployment_run')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise BartError(msg)

        # Attempt to release the DR
        log.debug('Attempting to release deployment run ID: {i}'.format(i=str(dr_id)))
        try:
            result = self.cons3rt_client.release_deployment_run(dr_id=dr_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to release deployment run ID: {i}\n{e}'.format(
                n=ex.__class__.__name__, i=str(dr_id), e=str(ex))
            raise BartError, msg, trace

        if result:
            log.info('Successfully released deployment run ID: {i}'.format(i=str(dr_id)))
        else:
            raise BartError('Unable to release deployment run ID: {i}'.format(i=str(dr_id)))

    def launch_deployment_run_from_json(self, deployment_id, json_file):
        """Launches a deployment run using options provided in a JSON file

        :return: (int) deployment run ID
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.launch_deployment_run_from_json')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise BartError(msg)

        # Ensure the json_file arg is a string
        if not isinstance(json_file, basestring):
            msg = 'The json_file arg must be a string'
            raise BartError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise BartError(msg)

        # Attempt to create the team
        try:
            dr_id = self.cons3rt_client.launch_deployment_run(deployment_id=deployment_id, json_file=json_file)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = '{n}: Unable to launch deployment run: {f}\n{e}'.format(
                n=ex.__class__.__name__, f=json_file, e=str(ex))
            raise BartError, msg, trace
        log.info('Successfully launched deployment run ID {i} from file: {f}'.format(i=dr_id, f=json_file))
        return dr_id

    def delete_inactive_runs_in_virtualization_realm(self, vr_id):
        """Deletes all inactive runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise BartError(msg)

        # List runs in the virtualization realm
        try:
            drs = self.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_INACTIVE')
        except BartError:
            _, ex, trace = sys.exc_info()
            msg = 'BartError: There was a problem listing inactive deployment runs in VR ID: {i}\n{e}'.format(
                i=str(vr_id), e=str(ex))
            raise BartError, msg, trace

        # Delete each inactive run
        log.debug('Found inactive runs in VR ID {i}:\n{r}'.format(i=str(vr_id), r=str(drs)))
        log.info('Attempting to delete inactive runs from VR ID: {i}'.format(i=str(vr_id)))
        for dr in drs:
            try:
                dr_id = dr['id']
            except KeyError:
                log.warn('Unable to determine the run ID from run: {r}'.format(r=str(dr)))
                continue
            try:
                self.delete_inactive_run(dr_id=dr_id)
            except BartError:
                _, ex, trace = sys.exc_info()
                log.warn('BartError: Unable to delete run ID: {i}\n{e}'.format(i=str(dr_id), e=str(ex)))
                continue
        log.info('Completed deleting inactive DRs in VR ID: {i}'.format(i=str(vr_id)))

    def release_active_runs_in_virtualization_realm(self, vr_id):
        """Releases all active runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.release_active_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise BartError(msg)

        # List active runs in the virtualization realm
        try:
            drs = self.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ACTIVE')
        except BartError:
            _, ex, trace = sys.exc_info()
            msg = 'BartError: There was a problem listing active deployment runs in VR ID: {i}\n{e}'.format(
                i=str(vr_id), e=str(ex))
            raise BartError, msg, trace

        # Release or cancel each active run
        log.debug('Found active runs in VR ID {i}:\n{r}'.format(i=str(vr_id), r=str(drs)))
        log.info('Attempting to release or cancel active runs from VR ID: {i}'.format(i=str(vr_id)))
        for dr in drs:
            try:
                dr_id = dr['id']
            except KeyError:
                log.warn('Unable to determine the run ID from run: {r}'.format(r=str(dr)))
                continue
            try:
                self.release_deployment_run(dr_id=dr_id)
            except BartError:
                _, ex, trace = sys.exc_info()
                log.warn('BartError: Unable to release or cancel run ID: {i}\n{e}'.format(i=str(dr_id), e=str(ex)))
                continue
        log.info('Completed releasing or cancelling active DRs in VR ID: {i}'.format(i=str(vr_id)))

    def delete_inactive_run(self, dr_id):
        """Deletes an inactive run

        :param dr_id: (int) deployment run ID
        :return: None
        :raises: BartError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_run')

        # Ensure the vr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise BartError(msg)

        log.debug('Attempting to delete run ID: {i}'.format(i=str(dr_id)))
        try:
            self.cons3rt_client.delete_deployment_run(dr_id=dr_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Cons3rtClientError: There was a problem deleting run ID: {i}\n{e}'.format(i=str(dr_id), e=str(ex))
            raise BartError, msg, trace
        else:
            log.info('Successfully deleted run ID: {i}'.format(i=str(dr_id)))

    def get_virtualization_realm_details(self, vr_id):
        """Queries for details of the virtualization realm ID

        :param vr_id: (int) VR ID
        :return: (dict) VR details
        """
        log = logging.getLogger(self.cls_logger + '.get_virtualization_realm_details')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise BartError(msg)

        # Query for VR details
        log.debug('Attempting query virtualization realm ID {i}'.format(i=str(vr_id)))
        try:
            vr_details = self.cons3rt_client.get_virtualization_realm_details(vr_id=vr_id)
        except Cons3rtClientError:
            _, ex, trace = sys.exc_info()
            msg = 'Unable to query CONS3RT for details on virtualization realm: {i}\n{e}'.format(
                i=str(vr_id), e=str(ex))
            raise BartError, msg, trace
        return vr_details


def config_pybart(config_file_path, cert_file_path=None):
    """Configure pyBart using a config file and optional cert from the
    ASSET_DIR/media directory

    :param: cert_file_path (str) name of the certificate pem file in the media directory
    :param: config_file_path (str) name of the config file
    :return: None
    """
    log = logging.getLogger(mod_logger + '.config_pybart')

    # Create the pybart directory
    log.info('Creating directory: {d}'.format(d=bart_config_dir))
    mkdir_p(bart_config_dir)

    # Ensure the config file exists
    if not os.path.isfile(config_file_path):
        raise BartError('Config file not found: {f}'.format(f=config_file_path))

    # Remove existing config file if it exists
    config_file_dest = os.path.join(bart_config_dir, 'config.json')
    if os.path.isfile(config_file_dest):
        log.info('Removing existing config file: {f}'.format(f=config_file_dest))
        os.remove(config_file_dest)

    # Copy files to the pybart dir
    log.info('Copying config file to directory: {d}'.format(d=bart_config_dir))
    shutil.copy2(config_file_path, config_file_dest)

    # Stage the cert if provided
    if cert_file_path:
        log.info('Attempting to stage certificate file: {f}'.format(f=cert_file_path))

        # Ensure the cert file exists
        if not os.path.isfile(cert_file_path):
            raise BartError('Certificate file not found: {f}'.format(f=cert_file_path))

        # Copy cert file to the pybart dir
        log.info('Copying certificate file to directory: {d}'.format(d=bart_config_dir))
        shutil.copy2(cert_file_path, bart_config_dir)
    else:
        log.info('No cert_file_path arg provided, no cert file will be copied.')


def validate_asset_structure(asset_dir_path):
    """Checks asset structure validity

    :param asset_dir_path: (str) path to the directory containing the asset
    :return: (str) Asset name
    :raises: Cons3rtAssetStructureError
    """
    log = logging.getLogger(mod_logger + '.validate_asset_structure')

    log.info('Validating asset directory: {d}'.format(d=asset_dir_path))

    # Acceptable items at the asset root
    acceptable_items = [
        'asset.properties',
        'scripts',
        'media',
        'config',
        'README',
        'HELP',
        'LICENSE',
        'HELP.md',
        'README.md',
        'LICENSE.md'
    ]

    # Acceptable dirs at the root
    acceptable_dirs = [
        'scripts',
        'media',
        'config'
    ]

    # Items to warn about
    warn_items = [
        'HELP.html',
        'README.html',
        'LICENSE.html'
    ]

    potential_doc_files = [
        'HELP.html',
        'README.html',
        'HELP',
        'README',
        'HELP.md',
        'README.md',
        'ALTERNATE_README'
    ]

    potential_license_files = [
        'LICENSE.html',
        'LICENSE',
        'LICENSE.md',
        'ALTERNATE_LICENSE'
    ]

    # Ensure there is an asset.properties file
    asset_props = os.path.join(asset_dir_path, 'asset.properties')

    if not os.path.isfile(asset_props):
        raise Cons3rtAssetStructureError('Asset properties file not found: {f}'.format(f=asset_props))

    # Props to find
    install_script_rel_path = None
    doc_file_rel_path = None
    license_file_rel_path = None
    asset_type = None
    license_file_path = ''
    doc_file_path = ''
    asset_name = None

    log.info('Reading asset properties file: {f}'.format(f=asset_props))
    with open(asset_props, 'r') as f:
        for line in f:
            if line.strip().startswith('installScript='):
                install_script_name = line.strip().split('=')[1]
                install_script_rel_path = os.path.join('scripts', install_script_name)
            elif line.strip().startswith('documentationFile='):
                doc_file_rel_path = line.strip().split('=')[1]
            elif line.strip().startswith('licenseFile='):
                license_file_rel_path = line.strip().split('=')[1]
            elif line.strip().startswith('assetType='):
                asset_type = line.strip().split('=')[1]
                asset_type = asset_type.lower()
            elif line.strip().startswith('name='):
                asset_name = line.strip().split('=')[1]

    # Ensure a name was provided
    if asset_name is None:
        raise Cons3rtAssetStructureError('Required property [name] not found in asset properties file: {f}'.format(
            f=asset_props))
    if asset_name == '':
        raise Cons3rtAssetStructureError('Required property [name] found blank in asset properties file: {f}'.format(
            f=asset_props))

    # Ensure asset_type was provided
    if asset_type is None:
        raise Cons3rtAssetStructureError('Required property [asset_type] not found in asset properties '
                                         'file: {f}'.format(f=asset_props))
    if asset_type == '':
        raise Cons3rtAssetStructureError('Required property [asset_type] found blank in asset properties '
                                         'file: {f}'.format(f=asset_props))

    log.info('Found installScript={f}'.format(f=install_script_rel_path))
    log.info('Found assetType={f}'.format(f=asset_type))

    # Verify the doc file exists if specified
    if doc_file_rel_path:
        log.info('Found documentationFile={f}'.format(f=doc_file_rel_path))
        doc_file_path = os.path.join(asset_dir_path, doc_file_rel_path)
        if not os.path.isfile(doc_file_path):
            raise Cons3rtAssetStructureError('Documentation file not found: {f}'.format(f=doc_file_path))
        else:
            log.info('Verified documentation file: {f}'.format(f=doc_file_path))
    else:
        log.info('The documentationFile property was not specified in asset.properties')

    # Verify the license file exists if specified
    if license_file_rel_path:
        log.info('Found licenseFile={f}'.format(f=license_file_rel_path))
        license_file_path = os.path.join(asset_dir_path, license_file_rel_path)
        if not os.path.isfile(license_file_path):
            raise Cons3rtAssetStructureError('License file not found: {f}'.format(f=license_file_path))
        else:
            log.info('Verified license file: {f}'.format(f=license_file_path))
    else:
        log.info('The licenseFile property was not specified in asset.properties')

    if asset_type == 'software':
        if not install_script_rel_path:
            raise Cons3rtAssetStructureError('Software asset has an asset.properties missing the installScript '
                                             'prop: {f}'.format(f=asset_props))
        else:
            install_script_path = os.path.join(asset_dir_path, install_script_rel_path)
            if not os.path.isfile(install_script_path):
                raise Cons3rtAssetStructureError('Install script file not found: {f}'.format(f=install_script_path))
            else:
                log.info('Verified install script for software asset: {f}'.format(f=install_script_path))

    log.info('Checking items at the root of the asset directory...')
    for item in os.listdir(asset_dir_path):
        log.info('Checking item: {i}'.format(i=item))
        item_path = os.path.join(asset_dir_path, item)
        if item_path == license_file_path:
            continue
        elif item_path == doc_file_path:
            continue
        elif item_path == asset_props:
            continue
        elif item in ignore_items:
            continue
        elif item in acceptable_dirs and os.path.isdir(item_path):
            continue
        else:
            if item == 'VERSION':
                os.remove(item_path)
                log.warn('Deleted file: {f}'.format(f=item_path))
            elif item == 'doc':
                raise Cons3rtAssetStructureError('Found a doc directory at the asset root, this is not allowed')
            elif item in potential_doc_files:
                if not doc_file_rel_path:
                    raise Cons3rtAssetStructureError('Documentation file found but not specified in '
                                                     'asset.properties: {f}'.format(f=item_path))
                else:
                    raise Cons3rtAssetStructureError('Extra documentation file found: {f}'.format(f=item_path))
            elif item in potential_license_files:
                if not license_file_rel_path:
                    raise Cons3rtAssetStructureError('License file found but not specified in '
                                                     'asset.properties: {f}'.format(f=item_path))
                else:
                    raise Cons3rtAssetStructureError('Extra license file found: {f}'.format(f=item_path))
            else:
                raise Cons3rtAssetStructureError('Found illegal item at the asset root dir: {i}'.format(i=item))
    log.info('Validated asset directory successfully: {d}'.format(d=asset_dir_path))
    return asset_name


def make_asset_zip(asset_dir_path, destination_directory=None):
    """Given an asset directory path, creates an asset zip file in the provided
    destination directory

    :param asset_dir_path: (str) path to the directory containing the asset
    :param destination_directory: (str) path to the destination directory for
            the asset
    :return: (str) Path to the asset zip file
    :raises: AssetZipCreationError
    """
    log = logging.getLogger(mod_logger + '.make_asset_zip')
    log.info('Attempting to create an asset zip from directory: {d}'.format(d=asset_dir_path))

    # Ensure the path is a directory
    if not os.path.isdir(asset_dir_path):
        raise AssetZipCreationError('Provided asset_dir_path is not a directory: {d}'.format(d=asset_dir_path))

    # Determine a destination directory if not provided
    if destination_directory is None:
        destination_directory = os.path.join(os.path.expanduser('~'), 'Downloads')
        mkdir_p(destination_directory)

    # Ensure the destination is a directory
    if not os.path.isdir(destination_directory):
        raise AssetZipCreationError('Provided destination_directory is not a directory: {d}'.format(
            d=destination_directory))

    # Validate the asset structure
    try:
        asset_name = validate_asset_structure(asset_dir_path=asset_dir_path)
    except Cons3rtAssetStructureError:
        _, ex, trace = sys.exc_info()
        msg = 'Cons3rtAssetStructureError: Problem found in the asset structure: {d}\n{e}'.format(
            d=asset_dir_path, e=str(ex))
        raise AssetZipCreationError, msg, trace

    # Determine the asset zip file name (same as asset name without spaces)
    zip_file_name = 'asset-' + asset_name.replace(' ', '') + '.zip'
    log.info('Using asset zip file name: {n}'.format(n=zip_file_name))

    # Determine the zip file path
    zip_file_path = os.path.join(destination_directory, zip_file_name)

    # Remove existing zip file if it exists
    if os.path.isfile(zip_file_path):
        log.info('Removing existing asset zip file: {f}'.format(f=zip_file_path))
        os.remove(zip_file_path)

    # Attempt to create the zip
    log.info('Attempting to create asset zip file: {f}'.format(f=zip_file_path))
    try:
        with contextlib.closing(zipfile.ZipFile(zip_file_path, 'w', allowZip64=True)) as zip_w:
            for root, dirs, files in os.walk(asset_dir_path):
                for f in files:
                    skip = False
                    file_path = os.path.join(root, f)

                    # Skip files in the ignore directories list
                    for ignore_dir in ignore_dirs:
                        if ignore_dir in file_path:
                            skip = True
                            break

                    # Skip file in the ignore files list
                    for ignore_file in ignore_files:
                        if f.startswith(ignore_file):
                            skip = True
                            break

                    if skip:
                        log.info('Skipping file: {f}'.format(f=file_path))
                        continue

                    log.info('Adding file to zip: {f}'.format(f=file_path))
                    archive_name = os.path.join(root[len(asset_dir_path):], f)
                    if archive_name.startswith('/'):
                        log.debug('Trimming the leading char: [/]')
                        archive_name = archive_name[1:]
                    log.info('Adding to archive as: {a}'.format(a=archive_name))
                    zip_w.write(file_path, archive_name)
    except Exception:
        _, ex, trace = sys.exc_info()
        msg = 'Unable to create zip file: {f}\n{e}'.format(f=zip_file_path, e=str(ex))
        raise AssetZipCreationError, msg, trace
    log.info('Successfully created asset zip file: {f}'.format(f=zip_file_path))
    return zip_file_path
