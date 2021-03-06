#!/usr/bin/python


class PyBartError(Exception):
    """This class is an Exception type for handling errors executing commands
    """
    pass


class HttpError(Exception):
    """This class in an Exception type for handling errors with rest client
    """
    pass


class Cons3rtClientError(Exception):
    """Simple exception type for handling errors with Cons3rtClient
    """
    pass


class Cons3rtAssetStructureError(Exception):
    """Simple exception type for handling errors with CONS3RT asset structure
    """
    pass


class AssetZipCreationError(Exception):
    """Simple exception type for handling errors creating the asset zip file
    """
    pass


class RestUser:

    def __init__(self, token, project=None, cert_file_path=None, username=None):
        self.token = token
        self.project_name = project
        self.cert_file_path = cert_file_path
        self.username = username

    def __str__(self):
        base_str = 'ReST User with token: {t}, for project: {p}'.format(t=self.token, p=self.project_name)
        if self.cert_file_path:
            return base_str + ', using cert auth: {c}'.format(c=self.cert_file_path)
        elif self.username:
            return base_str + ', using username auth: {u}'.format(u=self.username)
        else:
            return base_str
