# pybart Python Library for CONS3RT ReST Queries

Features
--------

- Utilities for making ReST queries to CONS3RT


pybart Set-Up
---

1. First clone and install [pycons3rt](https://github.com/cons3rt/pycons3rt)
1. Clone this repository `git clone git@github.com:cons3rt/pybart.git` 
1. Change to the pybart directory: `cd pybart`
1. Install pybart into your system python: `./scripts/install.sh`
1. Create the .pybart directory: `mkdir -p ~/.pybart`
1. Copy one of the sample config files in the `config` directory to `~/.pybart/config.json`.  Use the cert-based authentication sample for HmC.
1. Now you are ready to use pybart!

In your python code:

~~~
#!/usr/bin/env python

# import Bart
from pybart.bart import Bart, BartError, config_pybart

# Create the cons3rt_api
cons3rt_api = Bart(url='https://www.milcloud.hanscom.hpc.mil/rest/api/')

# Make cons3rt API calls

# list scenarios
scenarios = cons3rt_api.list_scenarios()

# retrieve active deployment runs
active_drs = cons3rt_api.list_deployment_runs_in_virtualization_realm(
    vr_id=10,
    search_type='SEARCH_ACTIVE'
)

# retrieve deployment run details
active_dr_details = cons3rt_api.retrieve_deployment_run_details(dr_id='12345')

# For some calls you can store a JSON file on the local file system and call
# with the path to the JSON file

# launch a deployment
dr_id = cons3r_api.launch_deployment_run_from_json(
    deployment_id='12345',
    json_file='/path/to/json/file.json'
)

~~~


pybart CONS3RT Assets
---

To create the pybart assets, from the pycons3rt repo root directory, run:

    $ ./scripts/make-assets.sh

This will create the Linux and Windows assets here:

    ./build/asset-pyBART-linux.zip
    ./build/asset-pyBART-windows.zip (coming soon)

Next, import your asset zip into CONS3RT.

#### Asset Prerequisites

1. Python (already installed on most Linux distros)
1. Git
1. [pycons3rt](https://github.com/cons3rt/pycons3rt) python package installed
1. Internet connectivity


#### Asset Exit Codes (Linux):

* 0 - Success
* 1 - Could not determine DEPLOYMENT_HOME
* 2 - deployment properties file not found
* 3 - Unable to resolve GIT server domain name
* 4 - Unable to clone git repo after 10 attempts
* 5 - There was a problem installing prerequisites for pyBART
* 6 - pybart install file not found, src may not have been checked out or staged correctly
* 7 - pybart install did not complete successfully 
* 8 - Non-zero exit code found, see the cons3rt agent log for more details

#### Asset Exit Codes (Windows)

* TBD

# pybart Documentation (coming soon)

TBD
