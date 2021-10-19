from setuptools import setup, find_packages

# support for post-install script execution
import atexit
from setuptools.command.develop import develop
from setuptools.command.install import install

import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / 'README.md').read_text(encoding='utf-8')

# Get the current version:
#djarango_version = __import__('djarango').get_version()
djarango_version = __import__('djarango').__version__

###################################
# post-install script classes
class PostDevelopCommand(develop):
    """ Post-installation for development mode."""
    def run(self):
        develop.run(self)
        # post install actions for developer build

class PostInstallCommand(install):
    """ Post-installation for development mode."""
    def run(self):
        install.run(self)
        # post install actions for official installation build

# post-install script - alternative method
def _post_install():
    print('POST INSTALL ACTIONS')

class new_install(install):
    def __init__(self, *args, **kwargs):
        super(new_install, self).__init__(*args, **kwargs)
        atexit.register(_post_install)


###################################
setup(
    name        = 'djarango',
    version     = djarango_version,

    description = 'ArangoDB Graph Database Backend for Django',
    long_description                = long_description,
    long_description_content_type   = 'text/markdown',

    url             = 'https://github.com/timothygraefe/djarango',
    author          = 'Timothy Graefe',
    author_email    = 'tgraefe@javamata.net',

    classifiers = [
        'Development Status :: 2 - Pre-Alpha',
        'Framework :: Django :: 2.2',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Intended Audience :: Developers',
        'Topic :: Database :: Front-Ends',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],

    keywords='django, arangodb, database, nosql',

    package_dir={'':'db'},
    packages=find_packages(where='db'),
    zip_safe=False,
    include_package_data=True,
    python_requires='>=3.6, <4',
    install_requires=['Django'],

    entry_points={
        'console_scripts': [
            'djarango=djarango:main',
        ],
    },

    project_urls={
        'Bug Reports': 'https://github.com/timothygraefe/djarango/issues',
        'Source': 'https://github.com/timothygraefe/imgutils/',
    },

    # post installation support
#   cmdclass = {
#       'develop' : PostDevelopCommand,
#       'install' : PostInstallCommand,
#   },

    # post installation support - alternative method
#   cmdclass = { 'install' : new_install, },

)



