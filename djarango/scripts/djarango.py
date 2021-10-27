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
            "db/backends/arangodb/version.py",
            "db/backends/arangodb/fields/edges.py",
            "db/backends/arangodb/fields/edge_descriptors.py", ]

################################################################################
# copied and adapted from Django setup.py
def get_env_pkgs(verbose):

    # Create a set of unique package distributions.
    pkgset = set()

    # base and site packages are for the "user" installed packages outside
    # of a virtual environment, e.g.: ${HOME}/.local/lib/python3.8/site-packages
    user_base = site.getuserbase()
    user_pkgs = site.getusersitepackages()
    pkgset.add(user_pkgs)

    # site pkgs list all site-packages and dist-packages directories for
    # the current environment, which may be a venv, or the default environment.
    # If it is a venv it will have a user-provided prefix, otherwise it will
    # indicate the usual /usr/lib, /usr/local, distributions.
    site_pkgs = site.getsitepackages()
    pkgset.update(site_pkgs)

    # lib_paths will be /usr/lib and /usr/local/lib dist-packages.
    # It may duplicate the same info found in site pkgs.
    lib_paths = [get_python_lib()]


    # Check if running in a virtual environment.
    # sys.prefix indicates the environment in use.  Either '/usr' or a
    # user-provided venv directory (e.g., ${HOME}/pkguser/).
    using_venv = (sys.prefix != sys.base_prefix)
    if verbose:
        print(f"\n  user base: {user_base}\n  user pkgs: {user_pkgs}\n")
        print(f"  sys.prefix        : {sys.prefix}")
        print(f"  sys.base_prefix   : {sys.base_prefix}")
        print(f"  using venv        : {using_venv}")
        for pkg in site_pkgs:
            print(f"  site pkg path: {pkg}")

    if lib_paths[0].startswith("/usr/lib/"):
        # Check with an explicit prefix of /usr/local in order to
        # catch Debian's custom user site-packages directory.
        lib_paths.append(get_python_lib(prefix="/usr/local"))

    pkgset.update(lib_paths)
    if verbose:
        for lib_path in lib_paths:
            print(f"  lib_path     : {lib_path}")

    if verbose:
        # add 1 for user_pkgs; len(user_pkgs) returns the length of the string.
        pkgsfound = 1 + len(site_pkgs) + len(lib_paths)
        unique    = len(pkgset)
        print(f"\n  Checked {pkgsfound} distributions and found {unique} unique")
        for pkg in sorted(pkgset):
            print(f"  pkg path: {pkg}")

    django_pkgs   = set()
    djarango_pkgs = set()
    django_pkg    = None
    djarango_pkg  = None
    linked        = False

    print(f"\n  Checking for installed Django / Djarango packages")
    for pkg_path in sorted(pkgset):
        django_path   = os.path.abspath(os.path.join(pkg_path, "django"))
        djarango_path = os.path.abspath(os.path.join(pkg_path, "djarango"))
        if verbose:
            print(f"    pkg_path: {pkg_path}")

        if os.path.exists(django_path):
            django_pkgs.add(django_path)
            if not using_venv:
                if django_path.startswith(user_pkgs):
                    django_pkg = django_path
            else:
                if django_path.startswith(sys.prefix):
                    django_pkg = django_path

        if os.path.exists(djarango_path):
            djarango_pkgs.add(djarango_path)
            if not using_venv:
                if djarango_path.startswith(user_pkgs):
                    djarango_pkg = djarango_path
            else:
                if django_path.startswith(sys.prefix):
                    djarango_pkg = djarango_path

    print(f"\n  Found {len(django_pkgs)} installed Django packages")
    for pkg in django_pkgs:
        print(f"   {pkg}")

    print(f"\n  Found {len(djarango_pkgs)} installed Djarango packages")
    for pkg in djarango_pkgs:
        print(f"   {pkg}")

    if not (django_pkg and djarango_pkg):
        print(f"\n  Did not find Django and Djarango in this environment")
        return None, None, linked

    print(f"\n  Found Django and Djarango packages in current environment:")
    if using_venv:
        print(f"    Virtual: {sys.prefix}")
    else:
        print(f"    User base: {user_pkgs}")

    # Check if link for ArangoDB backend exists and points to Djarango.
    arangodb_be     = os.path.join(django_pkg,   "db", "backends", "arangodb")
    djarango_target = os.path.join(djarango_pkg, "db", "backends", "arangodb")
    print(f"\n  Checking Django / Djarango Installation:\n    {arangodb_be}\n    {djarango_target}")
    if os.path.exists(arangodb_be):
        if verbose:
            print(f"  ArangoDB backend found:\n    {arangodb_be}")
        if os.path.islink(arangodb_be):
            target = os.readlink(arangodb_be)
            if target:
                # remove trailing / if it is there
                target = target.rstrip('/')
                if os.path.exists(target):
                    if verbose:
                        print(f"  ArangoDB successfully linked:\n    {arangodb_be}\n    {target}")
                    if target == djarango_target:
                        linked = True
                        print(f"\n  Djarango successfully installed and linked to Django:")
                        print(f"    Django:   \"{arangodb_be}\"\n    Djarango: \"{target}\"")
                else:
                    print(f"  ArangoDB link broken:\n    {arangodb_be}\n    {target}")
        else:
            print(f"  ArangoDB not found:\n    {arangodb_be}")

    return arangodb_be, djarango_target, linked


################################################################################
def check_status(verbose):

    adb_be, djarango_be, linked = get_env_pkgs(verbose)

    if not (adb_be and djarango_be):
        print(f"\n  Environment does not have Django and Djarango packages")
    else:
        print(f"\n  Environment has Django and Djarango packages.", end = '')
        if linked:
            print(f" Packages linked.")
        else:
            print(f" Packages not linked.")

################################################################################
def link_djarango(verbose):
    adb_be, djarango_be, linked = get_env_pkgs(verbose)

    if not (adb_be and djarango_be):
        print(f"\n  Environment does not have Django and Djarango packages")
        return

    print(f"\n  Environment has Django and Djarango packages")
    if linked:
        print(f"  Django and Djarango packages already linked")
        return

    print(f"  Django and Djarango packages not linked")

#   os.symlink(source, dest)  # link an existing source to a new dest link
    os.symlink(djarango_be, adb_be)
    print(f"  Created new Django backend link for ArangoDB via Djarango")
    print("")

################################################################################
def unlink_djarango(verbose):
    adb_be, djarango_be, linked = get_env_pkgs(verbose)

    if not (adb_be and djarango_be):
        print(f"\n  Environment does not have Django and Djarango packages")
        return

    print(f"\n  Environment has Django and Djarango packages")
    if not linked:
        print(f"  Django and Djarango packages not linked")
        return

    print(f"  Django and Djarango packages linked")
    print(f"  Unlinking {adb_be}")
    # unlink (i.e., delete) the destination link.
    # adb_be will be a link like: $pkg_lib/django/db/backends/arangodb
    os.unlink(adb_be)

def show_version(verbose):
    ver = get_version()
    print(f"\n  Build info -- version: {ver}\n\
                build date: {build_date}\n\
                build type: {build_type}\n")

################################################################################
def main():
    # Allow selection of a set of actions.
    dj_actions = [
        { 'fnp': check_status,    'desc' : "Check Djarango status", 'cmd': 'status', },
        { 'fnp': link_djarango,   'desc' : "Link Djarango",         'cmd': 'link', },
        { 'fnp': unlink_djarango, 'desc' : "Unlink Djarango",       'cmd': 'unlink', },
        { 'fnp': show_version,    'desc' : "Show Djarango version", 'cmd': 'version', },
    ]

    parser = argparse.ArgumentParser(description='Django/ArangoDB command line utility')

    parser.add_argument('action', metavar = 'command', nargs='?',
                            default='default', help='[status|link|unlink]')

#   parser.add_argument('--user', action='store_true', default=False, help='user install')
#   parser.add_argument('--global', action='store_true', default=False, help='global install')
    parser.add_argument('-V', action='store_true', default=False, help='verbose mode')

    args = parser.parse_args()

    action = args.action.lower() if args.action else None

    if action is None:
        print("")
        for tidx, item in enumerate(dj_actions):
            print("  Command: {:2} ({})".format(item[2] ,item[1]))
        print("")
        print("  Please select a specific command\n")
        return -1

    used_default = False
    if action == 'default':
        used_default = True
        action = 'status'

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
    fnp = dp['fnp']

    #user_install = '--user' in sys.argv[1:]
    user_install = False

    src_dir  = "env/src/djarango/"
    dest_dir = "site-packages/django/db/backends"

    verbose     = (args.V == True) or False

    if not used_default:
        print(f"\n  Running command: \'{action}\' ({dp['desc']})")

    # Finally call the function.
    fnp(verbose)
    return 0

################################################################################
################################################################################

### ### ### ### ### ### ### ### 
if __name__ == '__main__':
    main()

