import os
from setuptools import setup, find_packages

# support for post-install script execution
from setuptools.command.develop import develop
from setuptools.command.install import install

import pathlib

# Get the long description from the README file
here = pathlib.Path(__file__).parent.resolve()
long_description = (here / 'README.md').read_text(encoding='utf-8')

# Get the current version:
from djarango.scripts.djarango import make_version

###################################
# post-install script classes
class PostDevelopCommand(develop):
    """ Post-installation for development mode."""

    @staticmethod
    def djinstall():
        # post install actions for official installation build
        # print()'s are suppressed by pip, unless the "-vvv" option is used
        print('POST INSTALL ACTIONS (PostInstallCommand)')
        print("Linking djarango backend to django installation")
        os.system('djarango link --silent')
        print("Use 'djarango status' to check installation")
        return True

    def run(self):
        develop.run(self)
        PostDevelopCommand.djinstall()

class PostInstallCommand(install):
    """ Post-installation for install mode."""

    @staticmethod
    def djinstall():
        # post install actions for official installation build
        # print()'s are suppressed by pip, unless the "-vvv" option is used
        print('POST INSTALL ACTIONS (PostInstallCommand)')
        print("Linking djarango backend to django installation")
        os.system('djarango link --silent')
        print("Use 'djarango status' to check installation")
        return True

    def run(self):
        install.run(self)
        PostInstallCommand.djinstall()


###################################
setup(
    name        = 'djarango',
#   version     = '0.0.4',
    version     = make_version(),

    description = 'ArangoDB Graph Database Backend for Django',
    long_description                = long_description,
    long_description_content_type   = 'text/markdown',

    url             = 'https://github.com/timothygraefe/djarango',
    author          = 'Timothy Graefe',
    author_email    = 'tgraefe@javamata.net',
    license         = 'Apache',

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

#   package_dir={''},   # build fails - looking for a dict
#   package_dir={ '':''},
    #package_dir={'':'db'},
    #packages=find_packages(where='db'),
#   packages= [ 'db/backends/arangodb', ],  # doesn't work - looks for db/db/backends/arangodb
#                                           # because of package_dir directive above; worked
#                                           # after commenting out package_dir

#   packages= [ 'db/backends/arangodb', ],  # this works, but puts 'backends/arangodb' in
#                                           # in the site-packages directory for the source code
#                                           # I want source code in:
                                            #   site-packages/djarango/db/backends/arangodb
#                                           #   and scripts in:
                                            #   site-packages/djarango/scripts/

    packages= [ 'djarango/db/backends/arangodb',
                'djarango/db/backends/arangodb/fields',
                'djarango/scripts' ],

    # zip_safe and include_package_data may not be needed
    zip_safe=False,
    include_package_data=True,
    python_requires='>=3.6, <4',
    install_requires=['Django'],

    entry_points={
        'console_scripts': [
            'djarango=djarango.scripts.djarango:main',
        ],
    },

    project_urls={
        'Bug Reports': 'https://github.com/timothygraefe/djarango/issues',
        'Source': 'https://github.com/timothygraefe/imgutils/',
    },

    # post installation support
    cmdclass = {
#       'develop' : PostDevelopCommand,
        'install' : PostInstallCommand,
    },

    # post installation support - alternative method
#   cmdclass = { 'install' : new_install, },

)



