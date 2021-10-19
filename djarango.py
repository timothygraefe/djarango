#
# djarango.py
# config utility for Djarango backend
#

import os
import sys
import site
import re
import time
import argparse
import json
from datetime import datetime as dt
from distutils.sysconfig import get_python_lib
import django

build_ver = '0.0.3'
build_date = 'n/a'
build_type = 'n/a'

################################################################################
def get_version(pypi_build = False):
    global build_type, build_date

    if pypi_build:
        build_type = 'PyPI Upload'
    else:
        build_type = 'development'

    build_date = dt.now()

    return build_ver

################################################################################

pyfiles = [ "db/backends/arangodb/base.py",
            "db/backends/arangodb/client.py",
            "db/backends/arangodb/compiler.py",
            "db/backends/arangodb/creation.py",
            "db/backends/arangodb/features.py",
            "db/backends/arangodb/introspection.py",
            "db/backends/arangodb/operations.py",
            "db/backends/arangodb/schema.py",
            "db/backends/arangodb/fields/edges.py",
            "db/backends/arangodb/fields/edge_descriptors.py", ]

################################################################################
# copied and adapted from Django setup.py
def check_status(src_dir, dest_dir, use_user_dir, verbose):

#   site = { 'ENABLE_USER_SITE' : False }

    # Allow editable install into user site directory.
    # See https://github.com/pypa/pip/issues/7953.
#   site.ENABLE_USER_SITE = '--user' in sys.argv[1:]

    # Warn if we are installing over top of an existing installation. This can
    # cause issues where files that were deleted from a more recent Django are
    # still present in site-packages. See #18115.
    overlay_warning = False

    print(f"\n  sys.prefix: {sys.prefix}")
    if not use_user_dir:
        pkgs = site.getsitepackages()
        for pkg in pkgs:
            print(f"  pkg path: {pkg}")
    else:
        pkg = site.getusersitepackages()
        print(f"  user pkg path: {pkg} site.USER_BASE: {site['USER_BASE']}")

    lib_paths = [get_python_lib()]
    for lib_path in lib_paths:
        print(f"\n  lib_path: {lib_path}")

    if lib_paths[0].startswith("/usr/lib/"):
        # We have to try also with an explicit prefix of /usr/local in order to
        # catch Debian's custom user site-packages directory.
        lib_paths.append(get_python_lib(prefix="/usr/local"))
    for lib_path in lib_paths:
        existing_path = os.path.abspath(os.path.join(lib_path, "django"))
        print(f"\n  lib_path: {lib_path}\n  existing_path: {existing_path}")
        if os.path.exists(existing_path):
            # We note the need for the warning here, but present it after the
            # command is run, so it's more likely to be seen.
            print(f"  existing_path ({existing_path}) exists")
            overlay_warning = True
        else:
            print(f"  existing_path ({existing_path}) does not exist")

#   for pyfile in pyfiles:
#       cmd=f"  diff {src_dir}/djarango/{pyfile}\n    {dest_dir}/{pyfile}"
#       print(f"{cmd}")


################################################################################
def link_djarango(src_dir, dest_dir, use_user_dir, verbose):
    cmd = f"ln -s {src_dir} {dest_dir}"
    print(f"cmd = {cmd}")

#   for pyfile in pyfiles:
#       cmd="  cp -v -u {src_dir}/djarango/{pyfile}\n    {dest_dir}/{pyfile}"
#       print(f"cmd = {cmd}")
#       print(f"eval {cmd}")

################################################################################
def unlink_djarango(src_dir, dest_dir, use_user_dir, verbose):
    cmd = f"unlink {src_dir} {dest_dir}"
    print(f"cmd = {cmd}")

#   for pyfile in pyfiles:
#       cmd="  cp -v -u {src_dir}/djarango/{pyfile}\n    {dest_dir}/{pyfile}"
#       print(f"cmd = {cmd}")
#       print(f"eval {cmd}")

def show_version(src_dir, dest_dir, use_user_dir, verbose):
    ver = get_version()
    print(f"\n  Build info -- version: {ver}\n\
                build date: {build_date}\n\
                build type: {build_type}\n")

################################################################################
def main():
    # Allow selection of a set of actions.
    dj_actions = [
        { 'action': check_status,    'desc' : "Check Djarango status", 'cmd': 'status', },
        { 'action': link_djarango,   'desc' : "Link Djarango",         'cmd': 'link', },
        { 'action': unlink_djarango, 'desc' : "Unlink Djarango",       'cmd': 'unlink', },
        { 'action': show_version,    'desc' : "Show Djarango version", 'cmd': 'version', },
    ]

    parser = argparse.ArgumentParser(description='Django/ArangoDB command line utility')

    parser.add_argument('action', metavar = 'command', nargs = 1, type = str,
                            help='[status|link|unlink]')

    parser.add_argument('-V', action='store_true', default=False, help='verbose mode')
    args = parser.parse_args()

    action = args.action[0].lower() if args.action else None

    if action is None:
        print("")
        for tidx, item in enumerate(dj_actions):
            print("  Command: {:2} ({})".format(item[2] ,item[1]))
        print("")
        print("  Please select a specific command\n")
        return -1

    idx = [ x for x in range(len(dj_actions)) if dj_actions[x]['cmd'] == action ]
    if len(idx) == 0:
        # The command is not recognized.
        print(f"\n  Command \'{action}\' not recognized\n")
        print("  Available commands:\n")
        for tidx, item in enumerate(dj_actions):
            print("  ({}) Command: \'{:2}\'\t({})".format(tidx, item['cmd'] ,item['desc']))
        print("")
        return -1

    dp  = dj_actions[idx[0]]
    fnp = dp['action']

    use_user_dir = '--user' in sys.argv[1:]

    src_dir  = "env/src/djarango/"
    dest_dir = "site-packages/django/db/backends"

    verbose     = (args.V == True) or False

    print(f"\n  Running command: \'{action}\' ({dp['desc']})")
    fnp(src_dir, dest_dir, use_user_dir, verbose)
    return 0

################################################################################
################################################################################

### ### ### ### ### ### ### ### 
if __name__ == '__main__':
    main()
