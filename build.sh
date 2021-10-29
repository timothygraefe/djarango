#!/bin/bash

# check for local changes (0=no changes, 1=changes)
git diff-index --quiet --cached HEAD
staged=$?
git diff-files --quiet
file=$?
ufiles="$(git ls-files --others --exclude-standard)" && test -z "${ufiles}"
untracked=$?

echo -e "\nStarting build for djarango ..."
echo -e "  Checking for uncommitted changes (0=false/1=true):"
echo -e "    Staged files           : ${staged}"
echo -e "    Local file updates     : ${file}"
echo -e "    Untracked file changes : ${untracked}"
#echo "untracked files   : ${ufiles}"

echo -e "  Removing old build products (dist/*, djarango.egg-info/*)"
echo -e "    rm -rf dist/"
rm -rf dist/
echo -e "    rm -r djarango.egg-info/"
rm -rf djarango.egg-info/

echo -e "  Executing build ...\n"
python3 -m build

